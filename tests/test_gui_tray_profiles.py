import asyncio
import os
from collections.abc import Iterator
from dataclasses import replace
from typing import cast
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_support import opened, sync_run
from gui_tray_profiles_fakes import GatedClient, SelectingClient
from PySide6.QtWidgets import QApplication, QMessageBox

from naga_control.config import dump_toml, parse_toml
from naga_control.gui.app import MainWindow
from naga_control.gui.models import ServiceModel
from naga_control.gui.presenter import GuiPresenter
from naga_control.gui.tray_icon import TrayIcon
from naga_control.gui.worker import CoroFactory


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


def _page(window: MainWindow):  # pyright: ignore[reportUnknownParameterType]
    return window.device.profiles


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
    assert not hasattr(tray, "software_menu")
    assert tray.software_header.text() == "Software controls"
    assert tray.software_header_action is tray.software_header
    assert not tray.software_header.isEnabled()
    assert not tray.profile_menu.isEnabled()
    assert not tray.scroll_menu.isEnabled()
    assert not tray.onboard_menu.isEnabled()
    assert tray.device_mode.menu.isEnabled()
    assert not tray.profile_actions


def test_tray_owns_persistent_grouped_menu_and_show_quit_actions(
    qapp: QApplication, window: tuple[MainWindow, SelectingClient]
) -> None:
    widget, _client = window
    tray = _tray(widget)
    assert tray.icon.contextMenu() is tray.menu
    assert tray.menu.actions()[0] is tray.show_action
    assert tray.menu.actions()[1] is tray.software_header
    assert tray.profile_menu.menuAction() in tray.menu.actions()
    assert tray.scroll_menu.menuAction() in tray.menu.actions()
    assert tray.profile_menu.parent() is tray.menu
    assert tray.scroll_menu.parent() is tray.menu
    assert not hasattr(tray, "software_menu")
    assert tray.onboard_menu.menuAction() in tray.menu.actions()
    assert tray.device_mode.menu.menuAction() in tray.menu.actions()
    assert tray.menu.actions()[-1] is tray.quit_action
    order = tray.menu.actions()
    assert (
        order.index(tray.show_action)
        < order.index(tray.software_header)
        < order.index(tray.profile_menu.menuAction())
        < order.index(tray.scroll_menu.menuAction())
        < order.index(tray.onboard_menu.menuAction())
        < order.index(tray.device_mode.menu.menuAction())
        < order.index(tray.quit_action)
    )

    tray.show_action.trigger()
    qapp.processEvents()
    assert widget.isVisible()
    tray.show_action.trigger()
    assert not widget.isVisible()

    quit_app = Mock()
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
    page = _page(widget)
    assert set(tray.profile_actions) == {"first", "second", "third"}
    assert tray.profile_group.isExclusive()
    assert tray.profile_menu.title() == "Active software profile"
    assert tray.software_header.text() == "Software controls"
    assert tray.software_header_action is tray.software_header
    assert not hasattr(tray, "software_menu")
    assert tray.onboard_menu.title() == "Onboard / firmware"
    assert not hasattr(widget, "profiles_box")
    assert "not onboard slots" in tray.profile_menu.menuAction().toolTip()
    assert "does not apply the selected software profile" in page.profiles_box.toolTip()
    assert [action.text() for action in tray.profile_menu.actions()] == [
        "Same (first)",
        "Same (second)",
        "Third (third)",
    ]
    assert [page.profiles_box.itemText(i) for i in range(page.profiles_box.count())] == [
        action.text() for action in tray.profile_actions.values()
    ]
    assert [page.profiles_box.itemData(i) for i in range(page.profiles_box.count())] == [
        "first",
        "second",
        "third",
    ]
    assert all(action.isCheckable() for action in tray.profile_actions.values())
    assert _checked(tray) == ["first"]
    assert page.active_label.text().endswith("(first)")
    assert page.profiles_box.currentData() == "first"
    assert tray.profile_menu.isEnabled()
    assert tray.scroll_menu.isEnabled()
    assert tray.software_header.text() == "Software controls"
    assert not tray.software_header.isEnabled()
    assert not tray.onboard_menu.isEnabled()

    tray.profile_actions["second"].trigger()
    qapp.processEvents()
    assert client.selected == ["second"]
    assert parse_toml(client.document).active_profile == "second"
    assert _checked(tray) == ["second"]
    assert page.active_label.text().endswith("(second)")
    tray.profile_actions["second"].trigger()
    qapp.processEvents()
    assert client.selected == ["second"]
    assert _checked(tray) == ["second"]


def test_external_changes_rebuild_menu_and_update_active_label(
    qapp: QApplication, window: tuple[MainWindow, SelectingClient]
) -> None:
    widget, client = window
    tray = _tray(widget)
    page = _page(widget)
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
    assert page.profiles_box.itemText(page.profiles_box.findData("first")) == "Renamed (first)"
    assert _checked(tray) == ["second"]
    assert page.active_label.text().endswith("(second)")
    assert page.profiles_box.findData("third") == -1

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
    page = _page(widget)
    widget.model.mark_unreachable("offline")
    qapp.processEvents()
    assert not tray.profile_menu.isEnabled()
    assert not tray.scroll_menu.isEnabled()
    assert tray.software_header.text() == "Software controls"
    assert not page.activate_button.isEnabled()
    assert tray.device_mode.menu.isEnabled()
    tray.profile_actions["second"].trigger()
    qapp.processEvents()
    assert not client.selected
    assert _checked(tray) == ["first"]

    widget.model.mark_reachable()
    widget.model.apply_configuration(99, "not valid toml = [")
    qapp.processEvents()
    assert not tray.profile_menu.isEnabled()
    assert not tray.scroll_menu.isEnabled()
    assert not page.activate_button.isEnabled()
    tray.profile_actions["second"].trigger()
    qapp.processEvents()
    assert not client.selected
    widget.model.apply_configuration(100, client.document)
    qapp.processEvents()
    assert tray.profile_menu.isEnabled()
    assert tray.scroll_menu.isEnabled()
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
    page = _page(widget)
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
        assert page.active_label.text().endswith("(first)")
    else:
        assert not widget.settings.has_unsaved_changes()
        assert client.selected == ["second"]
        assert _checked(tray) == ["second"]
        assert page.active_label.text().endswith("(second)")


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
        page = _page(widget)
        tray.profile_actions["second"].trigger()
        assert len(jobs) == 1
        assert not tray.profile_menu.isEnabled()
        assert not tray.scroll_menu.isEnabled()
        assert not widget.device.isEnabled()
        assert _checked(tray) == ["first"]
        tray.profile_actions["third"].trigger()
        page.profiles_box.setCurrentIndex(page.profiles_box.findData("third"))
        page.activate_button.click()
        assert len(jobs) == 1
        assert _checked(tray) == ["first"]

        task = asyncio.create_task(jobs.pop()())
        await asyncio.wait_for(client.started.wait(), timeout=5)
        await presenter.refresh()
        qapp.processEvents()
        assert not tray.profile_menu.isEnabled()
        assert not tray.scroll_menu.isEnabled()
        assert _checked(tray) == ["first"]
        assert not task.done()
        assert client.selected == ["second"]

        client.finish.set()
        await asyncio.wait_for(task, timeout=5)
        qapp.processEvents()
        active = "first" if fail else "second"
        assert parse_toml(client.document).active_profile == active
        assert _checked(tray) == [active]
        assert page.active_label.text().endswith(f"({active})")
        assert tray.profile_menu.isEnabled()
        assert tray.scroll_menu.isEnabled()
        assert model.apply_status == ("Profile switch failed" if fail else "Profile switched")
        assert client.selected == ["second"]
        assert not jobs
    finally:
        client.finish.set()
        if task is not None:
            await task
        widget.deleteLater()
        qapp.processEvents()
