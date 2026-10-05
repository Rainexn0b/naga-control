import asyncio
import os
from collections.abc import Iterator
from dataclasses import replace
from typing import cast
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_support import FakeClient, opened, sync_run
from PySide6.QtWidgets import QApplication, QMessageBox

from naga_control.config import dump_toml, parse_toml
from naga_control.domain.defaults import default_configuration
from naga_control.gui.app import MainWindow
from naga_control.gui.models import ServiceModel
from naga_control.gui.presenter import GuiPresenter
from naga_control.gui.tray_icon import TrayIcon
from naga_control.gui.worker import CoroFactory
from naga_control.ipc.client import UnknownProfileError


def _document() -> str:
    base = default_configuration()
    profile = base.profile(base.active_profile)
    return dump_toml(
        replace(
            base,
            active_profile="first",
            default_profile="first",
            profiles=(
                ("first", replace(profile, display_name="Same")),
                ("second", replace(profile, display_name="Same")),
                ("third", replace(profile, display_name="Third")),
            ),
        )
    )


class SelectingClient(FakeClient):
    def __init__(self) -> None:
        super().__init__(_document())
        self.selected: list[str] = []

    async def select_profile(self, profile_id: str) -> int:
        self.selected.append(profile_id)
        config = parse_toml(self.document)
        config = replace(config, active_profile=profile_id, revision=config.revision + 1)
        self.document = dump_toml(config)
        return config.revision


class GatedClient(SelectingClient):
    def __init__(self, *, fail: bool) -> None:
        super().__init__()
        self.fail = fail
        self.started = asyncio.Event()
        self.finish = asyncio.Event()

    async def select_profile(self, profile_id: str) -> int:
        self.selected.append(profile_id)
        self.started.set()
        await self.finish.wait()
        if self.fail:
            raise UnknownProfileError("profile disappeared")
        config = parse_toml(self.document)
        config = replace(config, active_profile=profile_id, revision=config.revision + 1)
        self.document = dump_toml(config)
        return config.revision


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    yield cast(QApplication, app)


@pytest.fixture
def window(qapp: QApplication) -> Iterator[tuple[MainWindow, SelectingClient]]:
    client = SelectingClient()
    model = ServiceModel()
    presenter = GuiPresenter(model, open_client=lambda: opened(client))
    widget = MainWindow(presenter, model, sync_run)
    widget._poll_timer.stop()  # pyright: ignore[reportPrivateUsage]
    sync_run(presenter.refresh)
    qapp.processEvents()
    yield widget, client
    widget.deleteLater()
    qapp.processEvents()


def _tray(window: MainWindow) -> TrayIcon:
    tray = getattr(window, "_tray", None)
    assert tray is not None
    return tray


def _checked(tray: TrayIcon) -> list[str]:
    return [key for key, action in tray.profile_actions.items() if action.isChecked()]


def test_initial_offline_tray_has_no_profile_shortcuts(qapp: QApplication) -> None:
    tray = TrayIcon(
        ServiceModel(),
        toggle_window=lambda: None,
        select_profile=lambda _id: None,
        change_scroll=lambda _mode, _acceleration, _smart_reel: None,
        quit_app=lambda: None,
    )
    assert tray.icon.contextMenu() is tray.menu
    assert not tray.profile_menu.isEnabled()
    assert not tray.profile_actions


def test_tray_owns_persistent_context_menu_and_show_quit_actions(
    qapp: QApplication, window: tuple[MainWindow, SelectingClient]
) -> None:
    widget, _client = window
    tray = _tray(widget)
    assert tray.icon.contextMenu() is tray.menu
    assert tray.menu.actions()[0] is tray.show_action
    assert tray.profile_menu.menuAction() in tray.menu.actions()
    assert tray.menu.actions()[-1] is tray.quit_action

    tray.show_action.trigger()
    qapp.processEvents()
    assert widget.isVisible()
    tray.show_action.trigger()
    assert not widget.isVisible()

    quit_app = Mock()
    # The action's callback is bound at construction; test it on a standalone tray.
    standalone = TrayIcon(
        widget.model,
        toggle_window=lambda: None,
        select_profile=lambda _id: None,
        change_scroll=lambda _mode, _acceleration, _smart_reel: None,
        quit_app=quit_app,
    )
    assert standalone.icon.contextMenu() is standalone.menu
    standalone.quit_action.trigger()
    quit_app.assert_called_once_with()
    qapp.processEvents()


def test_profiles_are_exclusive_authoritative_and_id_based(
    qapp: QApplication, window: tuple[MainWindow, SelectingClient]
) -> None:
    widget, client = window
    tray = _tray(widget)
    assert set(tray.profile_actions) == {"first", "second", "third"}
    assert tray.profile_group.isExclusive()
    assert [action.text() for action in tray.profile_menu.actions()] == [
        "Same (first)",
        "Same (second)",
        "Third (third)",
    ]
    assert all(action.isCheckable() for action in tray.profile_actions.values())
    assert _checked(tray) == ["first"]
    assert widget.profiles_box.currentData() == "first"

    tray.profile_actions["second"].trigger()
    qapp.processEvents()
    assert client.selected == ["second"]
    assert parse_toml(client.document).active_profile == "second"
    assert _checked(tray) == ["second"]
    assert widget.profiles_box.currentData() == "second"
    tray.profile_actions["second"].trigger()
    qapp.processEvents()
    assert client.selected == ["second"]
    assert _checked(tray) == ["second"]


def test_external_changes_rebuild_menu_and_sync_header(
    qapp: QApplication, window: tuple[MainWindow, SelectingClient]
) -> None:
    widget, client = window
    tray = _tray(widget)
    config = parse_toml(client.document)
    client.document = dump_toml(
        replace(
            config,
            revision=config.revision + 1,
            active_profile="second",
            profiles=(
                ("first", replace(config.profile("first"), display_name="Renamed")),
                ("second", config.profile("second")),
            ),
        )
    )
    sync_run(widget.presenter.refresh)
    qapp.processEvents()
    assert set(tray.profile_actions) == {"first", "second"}
    assert tray.profile_actions["first"].text() == "Renamed (first)"
    assert _checked(tray) == ["second"]
    assert widget.profiles_box.currentData() == "second"
    assert widget.profiles_box.findData("third") == -1

    # A queued callback holding a removed ID must not select it after a refresh.
    tray._profile_requested("third")  # pyright: ignore[reportPrivateUsage]
    qapp.processEvents()
    assert client.selected == []
    assert _checked(tray) == ["second"]


def test_submenu_refreshes_after_remote_rename_while_parent_stays_open(
    qapp: QApplication, window: tuple[MainWindow, SelectingClient]
) -> None:
    widget, client = window
    tray = _tray(widget)
    tray.menu.show()
    tray.profile_menu.show()
    qapp.processEvents()
    assert tray.profile_menu.isVisible()
    old_action = tray.profile_actions["second"]
    config = parse_toml(client.document)
    client.document = dump_toml(
        replace(
            config,
            revision=config.revision + 1,
            profiles=(
                ("first", config.profile("first")),
                ("second", replace(config.profile("second"), display_name="Renamed")),
            ),
        )
    )
    sync_run(widget.presenter.refresh)
    qapp.processEvents()
    assert tray.profile_actions["second"] is old_action
    tray.profile_menu.hide()
    qapp.processEvents()
    tray.profile_menu.show()
    qapp.processEvents()
    assert tray.profile_actions["second"].text() == "Renamed (second)"
    assert set(tray.profile_actions) == {"first", "second"}
    tray.menu.hide()


def test_offline_and_unreadable_configuration_disable_selection(
    qapp: QApplication, window: tuple[MainWindow, SelectingClient]
) -> None:
    widget, client = window
    tray = _tray(widget)
    widget.model.mark_unreachable("offline")
    qapp.processEvents()
    assert not tray.profile_menu.isEnabled()
    assert not widget.profiles_box.isEnabled()
    tray.profile_actions["second"].trigger()
    qapp.processEvents()
    assert not client.selected
    assert _checked(tray) == ["first"]

    widget.model.mark_reachable()
    widget.model.apply_configuration(99, "not valid toml = [")
    qapp.processEvents()
    assert not tray.profile_menu.isEnabled()
    assert not widget.profiles_box.isEnabled()
    tray.profile_actions["second"].trigger()
    qapp.processEvents()
    assert not client.selected
    widget.model.apply_configuration(100, client.document)
    qapp.processEvents()
    assert tray.profile_menu.isEnabled()
    assert widget.profiles_box.isEnabled()
    assert _checked(tray) == ["first"]


@pytest.mark.parametrize("answer", [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes])
def test_hidden_draft_confirmation_preserves_or_discards(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    window: tuple[MainWindow, SelectingClient],
    answer: QMessageBox.StandardButton,
) -> None:
    widget, client = window
    tray = _tray(widget)
    widget.settings.dpi.rows[0].x_spin.setValue(2300)
    assert widget.settings.has_unsaved_changes()
    assert not widget.isVisible()
    question = Mock(return_value=answer)
    monkeypatch.setattr(QMessageBox, "question", question)

    tray.profile_actions["second"].trigger()
    qapp.processEvents()
    assert question.call_count == 1
    assert question.call_args.args[0] is None
    assert not widget.isVisible()
    if answer == QMessageBox.StandardButton.No:
        assert widget.settings.has_unsaved_changes()
        assert widget.settings.dpi.rows[0].x_spin.value() == 2300
        assert client.selected == []
        assert _checked(tray) == ["first"]
        assert widget.profiles_box.currentData() == "first"
    else:
        assert not widget.settings.has_unsaved_changes()
        assert client.selected == ["second"]
        assert _checked(tray) == ["second"]
        assert widget.profiles_box.currentData() == "second"


@pytest.mark.parametrize("fail", [False, True], ids=["success", "failure"])
async def test_pending_tray_switch_blocks_duplicates_and_reconciles(
    qapp: QApplication, fail: bool
) -> None:
    client = GatedClient(fail=fail)
    model = ServiceModel()
    presenter = GuiPresenter(model, open_client=lambda: opened(client))
    jobs: list[CoroFactory] = []
    widget = MainWindow(presenter, model, jobs.append)
    widget._poll_timer.stop()  # pyright: ignore[reportPrivateUsage]
    task: asyncio.Task[object] | None = None
    try:
        await presenter.refresh()
        qapp.processEvents()
        tray = _tray(widget)
        tray.profile_actions["second"].trigger()
        assert len(jobs) == 1
        assert not tray.profile_menu.isEnabled()
        assert not widget.profiles_box.isEnabled()
        assert _checked(tray) == ["first"]
        tray.profile_actions["third"].trigger()
        widget.profiles_box.setCurrentIndex(widget.profiles_box.findData("third"))
        assert len(jobs) == 1
        assert _checked(tray) == ["first"]

        task = asyncio.create_task(jobs.pop()())
        await asyncio.wait_for(client.started.wait(), timeout=5)
        await presenter.refresh()
        qapp.processEvents()
        assert not tray.profile_menu.isEnabled()
        assert not widget.profiles_box.isEnabled()
        assert _checked(tray) == ["first"]
        assert not task.done()
        assert client.selected == ["second"]

        client.finish.set()
        await asyncio.wait_for(task, timeout=5)
        qapp.processEvents()
        active = "first" if fail else "second"
        assert parse_toml(client.document).active_profile == active
        assert _checked(tray) == [active]
        assert widget.profiles_box.currentData() == active
        assert tray.profile_menu.isEnabled()
        assert widget.profiles_box.isEnabled()
        assert model.apply_status == ("Profile switch failed" if fail else "Profile switched")
        assert client.selected == ["second"]
        assert not jobs
    finally:
        client.finish.set()
        if task is not None:
            await task
        widget.deleteLater()
        qapp.processEvents()
