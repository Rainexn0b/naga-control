import asyncio
import os
from collections.abc import Iterator
from dataclasses import replace
from typing import Literal, cast
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_support import FakeClient, opened
from PySide6.QtWidgets import QApplication, QMessageBox

from naga_control.config import dump_toml, parse_toml
from naga_control.domain.defaults import default_configuration
from naga_control.gui.app import MainWindow
from naga_control.gui.models import ServiceModel
from naga_control.gui.presenter import ApplyOutcome, GuiPresenter
from naga_control.gui.tray_icon import TrayIcon
from naga_control.gui.worker import CoroFactory
from naga_control.ipc.client import UnknownProfileError


def _document() -> str:
    config = default_configuration()
    profile = config.profile(config.active_profile)
    return dump_toml(
        replace(
            config,
            profiles=(
                (config.active_profile, profile),
                ("other", replace(profile, display_name="Other")),
            ),
        )
    )


class GatedClient(FakeClient):
    def __init__(self, failure: Literal["unknown", "connection", "none"]) -> None:
        super().__init__(_document())
        self.failure = failure
        self.selected: list[str] = []
        self.started = asyncio.Event()
        self.finish = asyncio.Event()

    async def select_profile(self, profile_id: str) -> int:
        self.selected.append(profile_id)
        self.started.set()
        await self.finish.wait()
        if self.failure == "unknown":
            raise UnknownProfileError("profile disappeared")
        if self.failure == "connection":
            raise ConnectionError("service disconnected")
        config = parse_toml(self.document)
        config = replace(config, active_profile=profile_id, revision=config.revision + 1)
        self.document = dump_toml(config)
        return config.revision


class DelayedRefreshClient(FakeClient):
    def __init__(self) -> None:
        super().__init__(_document())
        self.delay = False
        self.started = asyncio.Event()
        self.finish = asyncio.Event()

    async def configuration_document(self) -> str:
        document = self.document
        if self.delay:
            self.delay = False
            self.started.set()
            await self.finish.wait()
        return document


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    yield cast(QApplication, app)


def _tray(window: MainWindow) -> TrayIcon:
    tray = window._tray  # pyright: ignore[reportPrivateUsage]
    assert tray is not None
    return tray


def _checked(tray: TrayIcon) -> list[str]:
    return [key for key, action in tray.profile_actions.items() if action.isChecked()]


def _dirty(window: MainWindow) -> None:
    window.settings.dpi.rows[0].x_spin.setValue(2300)
    window.buttons.rows[0].kind_box.setCurrentText("disabled")
    window.device.power.idle_spin.setValue(420)
    plate = window.device.profiles.plate_box
    plate.setCurrentIndex(plate.findData(6))
    _assert_drafts(window)


def _assert_drafts(window: MainWindow) -> None:
    assert window.settings.dpi.rows[0].x_spin.value() == 2300
    assert window.buttons.rows[0].kind_box.currentText() == "disabled"
    assert window.device.power.idle_spin.value() == 420
    assert window.device.profiles.plate_box.currentData() == 6
    for editor in (
        window.settings,
        window.buttons,
        window.device.power,
        window.device.profiles,
    ):
        assert editor.has_unsaved_changes()


@pytest.mark.parametrize("source", ["header", "tray"])
@pytest.mark.parametrize("visible", [False, True], ids=["hidden", "visible"])
@pytest.mark.parametrize(
    ("answer", "failure"),
    [
        (QMessageBox.StandardButton.No, "none"),
        (QMessageBox.StandardButton.Yes, "unknown"),
        (QMessageBox.StandardButton.Yes, "connection"),
        (QMessageBox.StandardButton.Yes, "none"),
    ],
    ids=["declined", "unknown-profile", "connection-lost", "applied"],
)
async def test_dirty_profile_switch_waits_for_confirmed_apply(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    source: Literal["header", "tray"],
    visible: bool,
    answer: QMessageBox.StandardButton,
    failure: Literal["unknown", "connection", "none"],
) -> None:
    client = GatedClient(failure)
    model = ServiceModel()
    presenter = GuiPresenter(model, open_client=lambda: opened(client))
    jobs: list[CoroFactory] = []
    window = MainWindow(presenter, model, jobs.append)
    window._poll_timer.stop()  # pyright: ignore[reportPrivateUsage]
    task: asyncio.Task[object] | None = None
    try:
        await presenter.refresh()
        if visible:
            window.show()
        qapp.processEvents()
        _dirty(window)
        tray = _tray(window)
        original = parse_toml(client.document)
        question = Mock(return_value=answer)
        monkeypatch.setattr(QMessageBox, "question", question)

        if source == "tray":
            tray.profile_actions["other"].trigger()
        else:
            window.profiles_box.setCurrentIndex(window.profiles_box.findData("other"))
        qapp.processEvents()
        question.assert_called_once()
        assert question.call_args.args[0] is (window if visible else None)
        _assert_drafts(window)
        assert _checked(tray) == [original.active_profile]
        if answer == QMessageBox.StandardButton.No:
            assert not jobs
            assert not client.selected
            assert window.profiles_box.currentData() == original.active_profile
            return

        assert len(jobs) == 1
        assert not window.profiles_box.isEnabled()
        assert not tray.profile_menu.isEnabled()
        # Neither entry point may enqueue a second request while one is pending.
        window.profiles_box.setCurrentIndex(window.profiles_box.findData("other"))
        tray.profile_actions["other"].trigger()
        assert len(jobs) == 1
        question.assert_called_once()
        _assert_drafts(window)

        task = asyncio.create_task(jobs.pop()())
        await asyncio.wait_for(client.started.wait(), timeout=5)
        await presenter.refresh()
        qapp.processEvents()
        assert not task.done()
        assert client.selected == ["other"]
        assert model.configuration_revision == original.revision
        assert window.profiles_box.currentData() == original.active_profile
        assert _checked(tray) == [original.active_profile]
        _assert_drafts(window)

        client.finish.set()
        await asyncio.wait_for(task, timeout=5)
        _assert_drafts(window)  # Queued Qt completion has not run yet.
        qapp.processEvents()
        applied = failure == "none"
        active = "other" if applied else original.active_profile
        assert parse_toml(client.document).active_profile == active
        assert window.profiles_box.currentData() == active
        assert _checked(tray) == [active]
        assert model.apply_status == ("Profile switched" if applied else "Profile switch failed")
        assert window.profiles_box.isEnabled() is (failure != "connection")
        assert tray.profile_menu.isEnabled() is (failure != "connection")
        assert client.selected == ["other"]
        if applied:
            for editor in (
                window.settings,
                window.buttons,
                window.device.power,
                window.device.profiles,
            ):
                assert not editor.has_unsaved_changes()
        else:
            _assert_drafts(window)
    finally:
        client.finish.set()
        if task is not None:
            await task
        window.deleteLater()
        qapp.processEvents()


async def test_delayed_refresh_cannot_undo_newer_apply_in_header_or_tray(
    qapp: QApplication,
) -> None:
    client = DelayedRefreshClient()
    model = ServiceModel()
    presenter = GuiPresenter(model, open_client=lambda: opened(client))
    jobs: list[CoroFactory] = []
    window = MainWindow(presenter, model, jobs.append)
    window._poll_timer.stop()  # pyright: ignore[reportPrivateUsage]
    task: asyncio.Task[None] | None = None
    try:
        await presenter.refresh()
        qapp.processEvents()
        old = client.document
        config = parse_toml(old)
        newer = dump_toml(replace(config, active_profile="other", revision=config.revision + 1))
        client.delay = True
        task = asyncio.create_task(presenter.refresh())
        await asyncio.wait_for(client.started.wait(), timeout=5)
        assert await presenter.apply_configuration(newer) is ApplyOutcome.APPLIED
        qapp.processEvents()
        tray = _tray(window)
        assert window.profiles_box.currentData() == "other"
        assert _checked(tray) == ["other"]
        notifications: list[bool] = []
        model.add_listener(lambda: notifications.append(True))

        client.finish.set()
        await asyncio.wait_for(task, timeout=5)
        qapp.processEvents()
        assert model.configuration_revision == config.revision + 1
        assert model.configuration_document == newer
        assert window.profiles_box.currentData() == "other"
        assert _checked(tray) == ["other"]
        assert not notifications
    finally:
        client.finish.set()
        if task is not None:
            await task
        window.deleteLater()
        qapp.processEvents()
