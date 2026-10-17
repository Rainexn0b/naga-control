"""Panel wiring, busy guards, restart confirmation, and hidden startup."""

import os
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_support import make_presenter, sync_run
from PySide6.QtWidgets import QApplication

from naga_control.gui import app as gui_app
from naga_control.gui.application_panel import ApplicationPanel
from naga_control.gui.device_page import DevicePage
from naga_control.gui.main_window import MainWindow
from naga_control.gui.service_restart import RestartResult
from tests.gui_application_fakes import FakeRestarter, make_store

VENV_ARGV = ["/tmp/venv/bin/python", "-m", "naga_control.gui.app", "--start-hidden"]


@pytest.fixture(scope="module")
def qapp() -> Any:
    app = QApplication.instance() or QApplication([])
    yield cast(QApplication, app)


def _panel(
    qapp: QApplication, tmp_path: Path, argv: list[str] | None = VENV_ARGV, confirm: Any = None
) -> tuple[ApplicationPanel, FakeRestarter, Any]:
    presenter, model, _client = make_presenter("")
    sync_run(presenter.refresh)
    store = make_store(tmp_path, argv)
    restarter = FakeRestarter()
    calls: list[str] = []

    def run(factory: Callable[[], Coroutine[Any, Any, object]]) -> None:
        calls.append("run")
        sync_run(factory)

    panel = ApplicationPanel(
        presenter, model, run, autostart=store, restarter=restarter, confirm=confirm
    )
    qapp.processEvents()
    qapp.processEvents()
    return panel, restarter, calls


def test_load_reports_owned_truth(qapp: QApplication, tmp_path: Path) -> None:
    panel, _restarter, _calls = _panel(qapp, tmp_path)
    assert panel.autostart_checkbox.isChecked() is False
    assert panel.autostart_error.text() == ""
    assert panel.autostart_checkbox.isEnabled()
    assert panel.restart_button.isEnabled()


def test_toggle_enables_and_disables(qapp: QApplication, tmp_path: Path) -> None:
    panel, _restarter, _calls = _panel(qapp, tmp_path)
    panel.autostart_checkbox.setChecked(True)
    qapp.processEvents()
    qapp.processEvents()
    assert panel.autostart_checkbox.isChecked() is True
    assert panel.autostart_error.text() == ""
    panel.autostart_checkbox.setChecked(False)
    qapp.processEvents()
    qapp.processEvents()
    assert panel.autostart_checkbox.isChecked() is False


def test_apply_failure_reverts_without_false_enabled(qapp: QApplication, tmp_path: Path) -> None:
    presenter, model, _client = make_presenter("")
    bad = make_store(tmp_path, None, error="Portable launcher unavailable.")
    restarter = FakeRestarter()

    def run(factory: Callable[[], Coroutine[Any, Any, object]]) -> None:
        sync_run(factory)

    panel = ApplicationPanel(
        presenter, model, run, autostart=bad, restarter=restarter, confirm=lambda: True
    )
    qapp.processEvents()
    qapp.processEvents()
    assert panel.autostart_checkbox.isChecked() is False
    assert panel.autostart_error.text() == ""
    panel.autostart_checkbox.setChecked(True)
    qapp.processEvents()
    qapp.processEvents()
    assert panel.autostart_checkbox.isChecked() is False
    assert panel.autostart_error.text() != ""
    assert not bad.path.exists()


def test_submit_failure_reverts_to_last_verified(qapp: QApplication, tmp_path: Path) -> None:
    import sys

    presenter, model, _client = make_presenter("")
    real_argv = [sys.executable, "-m", "naga_control.gui.app", "--start-hidden"]
    store = make_store(tmp_path, real_argv)
    assert store.apply(True).enabled is True
    restarter = FakeRestarter()

    def boom(factory: Callable[[], Coroutine[Any, Any, object]]) -> None:
        raise RuntimeError("worker gone")

    panel = ApplicationPanel(
        presenter, model, sync_run, autostart=store, restarter=restarter, confirm=lambda: True
    )
    qapp.processEvents()
    qapp.processEvents()
    assert panel.autostart_checkbox.isChecked() is True
    panel._run = boom  # type: ignore[method-assign]
    panel.autostart_checkbox.setChecked(False)
    qapp.processEvents()
    assert panel.autostart_checkbox.isChecked() is True
    assert "unavailable" in panel.autostart_error.text().lower()
    assert store.path.is_file()


def test_restart_needs_confirmation_no_command(qapp: QApplication, tmp_path: Path) -> None:
    panel, restarter, _calls = _panel(qapp, tmp_path, confirm=lambda: False)
    panel.restart_button.click()
    qapp.processEvents()
    assert restarter.calls == 0
    assert panel.restart_status.text() == ""


def test_restart_yes_runs_once_and_refreshes(qapp: QApplication, tmp_path: Path) -> None:
    presenter, model, _client = make_presenter("")
    sync_run(presenter.refresh)
    store = make_store(tmp_path, VENV_ARGV)
    restarter = FakeRestarter(RestartResult(ok=True))
    refresh_calls: list[str] = []
    orig_refresh = presenter.refresh

    async def counting_refresh() -> None:
        refresh_calls.append("refresh")
        await orig_refresh()

    presenter.refresh = counting_refresh  # type: ignore[method-assign]
    runs: list[str] = []

    def run(factory: Callable[[], Coroutine[Any, Any, object]]) -> None:
        runs.append("run")
        sync_run(factory)

    panel = ApplicationPanel(
        presenter, model, run, autostart=store, restarter=restarter, confirm=lambda: True
    )
    qapp.processEvents()
    qapp.processEvents()
    panel.restart_button.click()
    # Second click while the first completion is still queued must be ignored.
    panel.restart_button.click()
    qapp.processEvents()
    qapp.processEvents()
    qapp.processEvents()
    assert restarter.calls == 1
    assert runs != []
    assert refresh_calls != []
    assert panel.restart_status.text() == "Background service restarted."


def test_restart_reports_failure_without_fake_success(qapp: QApplication, tmp_path: Path) -> None:
    presenter, model, _client = make_presenter("")
    store = make_store(tmp_path, VENV_ARGV)
    restarter = FakeRestarter(RestartResult(ok=False, error="Service restart failed (exit 1)."))

    def run(factory: Callable[[], Coroutine[Any, Any, object]]) -> None:
        sync_run(factory)

    panel = ApplicationPanel(
        presenter, model, run, autostart=store, restarter=restarter, confirm=lambda: True
    )
    qapp.processEvents()
    qapp.processEvents()
    panel.restart_button.click()
    qapp.processEvents()
    qapp.processEvents()
    assert restarter.calls == 1
    assert "exit 1" in panel.restart_status.text()
    assert "ready" not in panel.restart_status.text().lower()


def test_restart_allowed_when_service_unreachable(qapp: QApplication, tmp_path: Path) -> None:
    presenter, model, _client = make_presenter("")
    model.mark_unreachable("lost")
    qapp.processEvents()
    store = make_store(tmp_path, VENV_ARGV)
    restarter = FakeRestarter()

    def run(factory: Callable[[], Coroutine[Any, Any, object]]) -> None:
        sync_run(factory)

    panel = ApplicationPanel(
        presenter, model, run, autostart=store, restarter=restarter, confirm=lambda: True
    )
    qapp.processEvents()
    qapp.processEvents()
    assert panel.restart_button.isEnabled()
    panel.restart_button.click()
    qapp.processEvents()
    qapp.processEvents()
    assert restarter.calls == 1


def test_missing_capability_disables_not_snapshot(qapp: QApplication) -> None:
    presenter, model, _client = make_presenter("")
    panel = ApplicationPanel(presenter, model, sync_run, autostart=None, restarter=None)
    assert not panel.autostart_checkbox.isEnabled()
    assert not panel.restart_button.isEnabled()
    assert "unavailable" in panel.autostart_error.text().lower()


def test_device_page_wiring(qapp: QApplication, tmp_path: Path) -> None:
    presenter, model, _client = make_presenter("")
    store = make_store(tmp_path, VENV_ARGV)
    restarter = FakeRestarter()
    page = DevicePage(
        presenter,
        model,
        sync_run,
        autostart=store,
        restarter=restarter,
        application_confirm=lambda: True,
    )
    qapp.processEvents()
    qapp.processEvents()
    assert page.application is not None
    assert page.application.autostart_checkbox is not None
    assert page.application.restart_button is not None
    bare_presenter, bare_model, _ = make_presenter("")
    bare = DevicePage(bare_presenter, bare_model, sync_run)
    assert bare.application is None


def test_main_window_without_caps_makes_no_host_actions(qapp: QApplication) -> None:
    presenter, model, _client = make_presenter("")
    window = MainWindow(presenter, model, sync_run)
    window._poll_timer.stop()  # type: ignore[attr-defined]
    assert window.device.application is None
    assert window.tabs.count() == 3


def test_wants_hidden_flag() -> None:
    assert gui_app.wants_hidden(["--start-hidden"]) is True
    assert gui_app.wants_hidden([]) is False
    assert gui_app.wants_hidden(["gui", "--start-hidden"]) is True


def _main_with_mocks(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    *,
    tray_available: bool,
    duplicate: bool,
) -> tuple[int, list[str], list[object], list[str]]:
    calls: list[str] = []
    shown: list[str] = []
    created: list[object] = []

    class FakeApp:
        @staticmethod
        def setDesktopFileName(name: str) -> None:
            calls.append(f"desktop:{name}")

        def __init__(self, _argv: list[str]) -> None:
            calls.append("application")

        def setWindowIcon(self, _icon: object) -> None:
            pass

        def setQuitOnLastWindowClosed(self, _enabled: bool) -> None:
            pass

        def exec(self) -> int:
            return 0

    class FakeInstanceObj:
        def set_window(self, _window: object) -> None:
            pass

        def close(self) -> None:
            pass

    class FakeInstanceCls:
        @staticmethod
        def start(*_args: object, **_kwargs: object) -> object | None:
            calls.append("instance")
            return None if duplicate else FakeInstanceObj()

    class FakeWorker:
        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

        def submit(self, _factory: object) -> Any:
            import concurrent.futures

            future: concurrent.futures.Future[object] = concurrent.futures.Future()
            future.set_result(None)
            return future

    class FakeWindow:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            created.append(self)

        def show(self) -> None:
            shown.append("show")

    monkeypatch.setattr(gui_app, "QApplication", FakeApp)
    monkeypatch.setattr(gui_app, "GuiInstance", FakeInstanceCls)
    monkeypatch.setattr(gui_app, "LoopWorker", FakeWorker)
    monkeypatch.setattr(gui_app, "MainWindow", FakeWindow)
    monkeypatch.setattr(
        gui_app.QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: tray_available)
    )
    code = gui_app.main(argv)
    return code, shown, created, calls


def test_hidden_stays_hidden_with_tray(monkeypatch: pytest.MonkeyPatch) -> None:
    code, shown, created, calls = _main_with_mocks(
        monkeypatch, ["--start-hidden"], tray_available=True, duplicate=False
    )
    assert code == 0
    assert len(created) == 1
    assert shown == []
    assert calls[:3] == ["desktop:org.nagacontrol.NagaControl", "application", "instance"]


def test_hidden_falls_back_without_tray(monkeypatch: pytest.MonkeyPatch) -> None:
    code, shown, created, _calls = _main_with_mocks(
        monkeypatch, ["--start-hidden"], tray_available=False, duplicate=False
    )
    assert code == 0
    assert len(created) == 1
    assert shown == ["show"]


def test_manual_start_is_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    code, shown, created, _calls = _main_with_mocks(
        monkeypatch, [], tray_available=True, duplicate=False
    )
    assert code == 0
    assert len(created) == 1
    assert shown == ["show"]


def test_duplicate_hidden_creates_no_window(monkeypatch: pytest.MonkeyPatch) -> None:
    code, shown, created, _calls = _main_with_mocks(
        monkeypatch, ["--start-hidden"], tray_available=True, duplicate=True
    )
    assert code == 0
    assert created == []
    assert shown == []
