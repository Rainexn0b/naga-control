"""Restart helper: fixed argv, cleanup, timeout, redaction (no host units)."""

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_support import make_presenter, sync_run
from PySide6.QtWidgets import QApplication

from naga_control.gui import application_panel as ap_mod
from naga_control.gui.main_window import MainWindow
from naga_control.gui.service_restart import RESTART_ARGV, RestartResult, restart_service
from tests.gui_application_fakes import FakeRestarter, make_store

EXPECTED = ("systemctl", "--user", "restart", "naga-control.service")


class FakeProc:
    def __init__(self, code: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.returncode: int | None = None
        self._code = code
        self._out = stdout
        self._err = stderr
        self.killed = False
        self.waited = False

    async def communicate(self) -> tuple[bytes, bytes]:
        self.returncode = self._code
        return self._out, self._err

    async def wait(self) -> int:
        self.waited = True
        if self.returncode is None:
            self.returncode = self._code
        return self.returncode

    def kill(self) -> None:
        self.killed = True


def test_argv_is_fixed_user_unit_only() -> None:
    assert tuple(RESTART_ARGV) == EXPECTED
    assert RESTART_ARGV.count("naga-control.service") == 1
    assert "--user" in RESTART_ARGV
    assert "sudo" not in RESTART_ARGV and "enable" not in RESTART_ARGV


async def test_success_calls_exact_argv() -> None:
    seen: list[tuple[tuple[str, ...], dict[str, object]]] = []
    proc = FakeProc(code=0)

    async def create(*argv: str, **kwargs: object) -> FakeProc:
        seen.append((argv, kwargs))
        return proc

    result = await restart_service(create_process=create)  # type: ignore[arg-type]
    assert result.ok is True and result.error is None
    assert len(seen) == 1
    assert seen[0][0] == EXPECTED
    assert proc.returncode == 0 and not proc.killed


async def test_nonzero_reports_exit_without_stderr() -> None:
    secret = b"secret-token-xyz\nsecond line"
    proc = FakeProc(code=1, stdout=b"", stderr=secret)

    async def create(*argv: str, **kwargs: object) -> FakeProc:
        assert argv == EXPECTED
        return proc

    result = await restart_service(create_process=create)  # type: ignore[arg-type]
    assert result.ok is False
    assert result.error is not None and "exit 1" in result.error
    assert "secret-token-xyz" not in result.error and "\n" not in result.error


async def test_missing_systemctl_is_clear_error() -> None:
    async def create(*argv: str, **kwargs: object) -> FakeProc:
        raise FileNotFoundError("no systemctl")

    result = await restart_service(create_process=create)  # type: ignore[arg-type]
    assert result.ok is False
    assert result.error is not None and "not found" in result.error.lower()


async def test_timeout_kills_and_joins() -> None:
    class HangingProc(FakeProc):
        async def communicate(self) -> tuple[bytes, bytes]:
            await asyncio.sleep(60)
            return b"", b""

    proc = HangingProc()

    async def create(*argv: str, **kwargs: object) -> HangingProc:
        return proc

    result = await restart_service(timeout=0.02, create_process=create)  # type: ignore[arg-type]
    assert result.ok is False
    assert result.error is not None and "timed out" in result.error.lower()
    assert "uncertain" in result.error.lower() and "check status" in result.error.lower()
    assert "secret" not in result.error.lower()
    assert proc.killed is True and proc.waited is True


async def test_cleanup_unverified_when_join_hangs() -> None:
    class StuckProc(FakeProc):
        async def communicate(self) -> tuple[bytes, bytes]:
            await asyncio.sleep(60)
            return b"", b""

        async def wait(self) -> int:
            self.waited = True
            await asyncio.sleep(60)
            return 0

    proc = StuckProc()

    async def create(*argv: str, **kwargs: object) -> StuckProc:
        return proc

    result = await restart_service(timeout=0.02, create_process=create)  # type: ignore[arg-type]
    assert result.ok is False
    assert result.error is not None and "unverified" in result.error.lower()
    assert "uncertain" in result.error.lower()
    assert proc.killed is True


async def test_cancel_kills_and_reraise() -> None:
    started = asyncio.Event()
    proc = FakeProc(code=0)

    async def slow_communicate() -> tuple[bytes, bytes]:
        started.set()
        await asyncio.sleep(60)
        return b"", b""

    proc.communicate = slow_communicate  # type: ignore[method-assign]

    async def create(*argv: str, **kwargs: object) -> FakeProc:
        return proc

    task = asyncio.create_task(restart_service(timeout=5.0, create_process=create))  # type: ignore[arg-type]
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert proc.killed is True and proc.waited is True


async def test_double_cancel_still_joins() -> None:
    started = asyncio.Event()
    allow = asyncio.Event()
    proc = FakeProc(code=0)

    async def slow_communicate() -> tuple[bytes, bytes]:
        started.set()
        await asyncio.sleep(60)
        return b"", b""

    async def gated_wait() -> int:
        proc.waited = True
        await allow.wait()
        if proc.returncode is None:
            proc.returncode = 0
        return 0

    proc.communicate = slow_communicate  # type: ignore[method-assign]
    proc.wait = gated_wait  # type: ignore[method-assign]

    async def create(*argv: str, **kwargs: object) -> FakeProc:
        return proc

    task = asyncio.create_task(restart_service(timeout=5.0, create_process=create))  # type: ignore[arg-type]
    await started.wait()
    task.cancel()
    await asyncio.sleep(0.02)
    task.cancel()
    allow.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert proc.killed is True and proc.waited is True


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    yield cast(QApplication, app)


def _window(
    qapp: QApplication, tmp_path: Path, restarter: FakeRestarter
) -> tuple[MainWindow, object]:
    presenter, model, client = make_presenter("")
    store = make_store(
        tmp_path, ["/tmp/venv/bin/python", "-m", "naga_control.gui.app", "--start-hidden"]
    )
    window = MainWindow(
        presenter,
        model,
        sync_run,
        autostart=store,
        restarter=restarter,
        application_confirm=lambda: True,
    )
    window._poll_timer.stop()  # pyright: ignore[reportPrivateUsage]
    sync_run(presenter.refresh)
    qapp.processEvents()
    qapp.processEvents()
    assert window.device.application is not None
    return window, client


async def _async_window(
    qapp: QApplication, tmp_path: Path, restarter: Any
) -> tuple[Any, Any, Any, Any, list[asyncio.Task[object]]]:
    presenter, model, _ = make_presenter("")
    await presenter.refresh()
    store = make_store(
        tmp_path, ["/tmp/venv/bin/python", "-m", "naga_control.gui.app", "--start-hidden"]
    )
    tasks: list[asyncio.Task[object]] = []

    def run(factory: object) -> None:
        tasks.append(asyncio.create_task(factory()))  # type: ignore[operator]

    window = MainWindow(
        presenter,
        model,
        run,  # type: ignore[arg-type]
        autostart=store,
        restarter=restarter,
        application_confirm=lambda: True,
    )
    window._poll_timer.stop()  # pyright: ignore[reportPrivateUsage]
    qapp.processEvents()
    qapp.processEvents()
    await asyncio.wait_for(asyncio.gather(*tasks), 2.0)
    tasks.clear()
    qapp.processEvents()
    qapp.processEvents()
    assert window.device.application is not None
    return window, presenter, model, window.device.application, tasks


def test_restart_preserves_real_drafts(qapp: QApplication, tmp_path: Path) -> None:
    restarter = FakeRestarter(RestartResult(ok=True))
    window, _client = _window(qapp, tmp_path, restarter)
    panel = window.device.application
    assert panel is not None
    window.device.power.idle_spin.setValue(600)
    window.buttons.rows[0].kind_box.setCurrentText("mouse_button")
    assert window.device.has_unsaved_changes()
    before = (window.device.power.idle_spin.value(), window.buttons.rows[0].kind_box.currentText())
    panel.restart_button.click()
    qapp.processEvents()
    qapp.processEvents()
    qapp.processEvents()
    assert restarter.calls == 1
    assert window.device.has_unsaved_changes()
    assert (
        window.device.power.idle_spin.value(),
        window.buttons.rows[0].kind_box.currentText(),
    ) == before
    assert panel.restart_status.text() == "Background service restarted."
    window.close()


def test_guard_blocks_profile_while_restart_busy(qapp: QApplication, tmp_path: Path) -> None:
    restarter = FakeRestarter(RestartResult(ok=True))
    window, _client = _window(qapp, tmp_path, restarter)
    window.device.power.idle_spin.setValue(600)
    assert window.device.has_unsaved_changes()
    assert window._restart_guard.begin_restart() is True  # pyright: ignore[reportPrivateUsage]
    assert not window.device.isEnabled()
    # Profile dispatch must refuse while restart holds the guard.
    window._request_profile("mmo")  # pyright: ignore[reportPrivateUsage]
    qapp.processEvents()
    assert window._profile_switching is False  # pyright: ignore[reportPrivateUsage]
    assert window.device.has_unsaved_changes()
    # Panel must also refuse a second restart while busy.
    panel = window.device.application
    assert panel is not None
    panel.request_restart()
    assert restarter.calls == 0
    assert "progress" in panel.restart_status.text().lower()
    window._restart_guard.end_restart()  # pyright: ignore[reportPrivateUsage]
    qapp.processEvents()
    assert window.device.isEnabled()
    assert window.device.has_unsaved_changes()
    window.close()


def test_panel_refuses_when_apply_busy(qapp: QApplication, tmp_path: Path) -> None:
    restarter = FakeRestarter(RestartResult(ok=True))
    window, _client = _window(qapp, tmp_path, restarter)
    window._profile_switching = True  # pyright: ignore[reportPrivateUsage]
    panel = window.device.application
    assert panel is not None
    panel.request_restart()
    qapp.processEvents()
    assert restarter.calls == 0
    assert "progress" in panel.restart_status.text().lower()
    window._profile_switching = False  # pyright: ignore[reportPrivateUsage]
    window._restart_guard.end_restart()  # pyright: ignore[reportPrivateUsage]
    window.close()


async def test_restart_refresh_hang_marks_unverified(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ap_mod, "_POST_RESTART_REFRESH_TIMEOUT", 0.05)
    restarter = FakeRestarter(RestartResult(ok=True))
    window, presenter, model, panel, tasks = await _async_window(qapp, tmp_path, restarter)
    assert model.connection.reachable
    entered = asyncio.Event()

    async def hanging_refresh() -> None:
        entered.set()
        await asyncio.Event().wait()

    presenter.refresh = hanging_refresh  # type: ignore[method-assign]
    window.device.power.idle_spin.setValue(600)
    window.buttons.rows[0].kind_box.setCurrentText("mouse_button")
    assert window.device.has_unsaved_changes()
    before = (
        window.device.power.idle_spin.value(),
        window.buttons.rows[0].kind_box.currentText(),
    )
    panel.restart_button.click()
    await asyncio.wait_for(entered.wait(), 1.0)
    assert restarter.calls == 1
    assert not panel.restart_button.isEnabled()
    await asyncio.wait_for(asyncio.gather(*tasks), 2.0)
    qapp.processEvents()
    qapp.processEvents()
    await asyncio.wait_for(asyncio.gather(*tasks), 2.0)
    qapp.processEvents()
    assert restarter.calls == 1
    assert not model.connection.reachable
    assert "unverified" in (model.connection.detail or "").lower()
    assert window.device.has_unsaved_changes()
    assert (
        window.device.power.idle_spin.value(),
        window.buttons.rows[0].kind_box.currentText(),
    ) == before
    text = panel.restart_status.text()
    assert "Background service restarted" in text
    assert "unverified" in text.lower() and "check status" in text.lower()
    assert panel.restart_button.isEnabled()
    assert window.device.isEnabled()
    window.close()


async def test_restart_cancel_releases_guard_with_uncertain(
    qapp: QApplication, tmp_path: Path
) -> None:
    started = asyncio.Event()
    calls: list[str] = []

    async def hanging_restarter() -> RestartResult:
        calls.append("call")
        started.set()
        await asyncio.Event().wait()
        return RestartResult(ok=True)

    window, _presenter, model, panel, tasks = await _async_window(qapp, tmp_path, hanging_restarter)
    window.device.power.idle_spin.setValue(600)
    assert window.device.has_unsaved_changes()
    panel.restart_button.click()
    await asyncio.wait_for(started.wait(), 1.0)
    assert len(tasks) == 1
    tasks[0].cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(asyncio.gather(*tasks), 2.0)
    qapp.processEvents()
    qapp.processEvents()
    remaining = [t for t in tasks if not t.done()]
    if remaining:
        await asyncio.wait_for(asyncio.gather(*remaining), 2.0)
    qapp.processEvents()
    qapp.processEvents()
    assert calls == ["call"]
    assert not model.connection.reachable
    assert "unverified" in (model.connection.detail or "").lower()
    assert window.device.has_unsaved_changes()
    text = panel.restart_status.text()
    assert "uncertain" in text.lower() and "check status" in text.lower()
    assert panel.restart_button.isEnabled()
    assert window.device.isEnabled()
    window.close()
