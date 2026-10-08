"""Flattened tray sections: header plus direct profile/scroll menus."""

import os
from collections.abc import Iterator
from typing import cast
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu

from naga_control.config import dump_toml
from naga_control.domain.defaults import default_configuration
from naga_control.gui.models import ServiceModel, ServiceSnapshotView
from naga_control.gui.profile_mode_view import MODE_SWITCH_GATE
from naga_control.gui.tray_icon import TrayIcon


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    yield cast(QApplication, app)


@pytest.fixture
def tray(qapp: QApplication) -> Iterator[TrayIcon]:
    widget = TrayIcon(
        ServiceModel(),
        toggle_window=Mock(),
        select_profile=Mock(),
        change_scroll=Mock(),
        quit_app=Mock(),
    )
    yield widget
    widget.icon.hide()
    widget.menu.close()
    widget.deleteLater()
    qapp.processEvents()


def _admit_verified_software(tray: TrayIcon, qapp: QApplication) -> None:
    tray.model.apply_configuration(1, dump_toml(default_configuration()))
    tray.model.apply_snapshot(
        ServiceSnapshotView(
            "available",
            1,
            "hyperspeed",
            None,
            desired_mode="software",
            observed_mode="software",
            mode_ready=True,
        )
    )
    qapp.processEvents()


def test_root_sequence_and_parent_ownership(qapp: QApplication, tray: TrayIcon) -> None:
    _admit_verified_software(tray, qapp)
    order = tray.menu.actions()
    assert order[0] is tray.show_action
    assert order[1] is tray.software_header
    assert tray.profile_menu.menuAction() in order
    assert tray.scroll_menu.menuAction() in order
    assert tray.onboard_menu.menuAction() in order
    assert tray.device_mode.menu.menuAction() in order
    assert order[-1] is tray.quit_action
    assert (
        order.index(tray.show_action)
        < order.index(tray.software_header)
        < order.index(tray.profile_menu.menuAction())
        < order.index(tray.scroll_menu.menuAction())
        < order.index(tray.onboard_menu.menuAction())
        < order.index(tray.device_mode.menu.menuAction())
        < order.index(tray.quit_action)
    )
    assert tray.profile_menu.parent() is tray.menu
    assert tray.scroll_menu.parent() is tray.menu
    assert tray.onboard_menu.parent() is tray.menu
    assert tray.device_mode.menu.parent() is tray.menu
    separators = [action for action in order if action.isSeparator()]
    assert len(separators) >= 2
    assert order.index(tray.scroll_menu.menuAction()) < order.index(separators[0])
    assert order.index(separators[0]) < order.index(tray.onboard_menu.menuAction())


def test_header_is_bold_disabled_readonly_action(qapp: QApplication, tray: TrayIcon) -> None:
    _admit_verified_software(tray, qapp)
    header = tray.software_header
    assert tray.software_header_action is header
    assert isinstance(header, QAction)
    assert not isinstance(header, QMenu)
    assert header.text() == "Software controls"
    assert not header.isEnabled()
    assert not header.isCheckable()
    assert not header.isSeparator()
    assert header.font().bold()
    tooltip = header.toolTip().lower()
    assert "software" in tooltip
    assert "profile" in tooltip
    assert "scroll" in tooltip
    assert header.menu() is None  # pyright: ignore[reportUnnecessaryComparison]
    header.trigger()
    qapp.processEvents()
    for name in ("_toggle_window", "_select_profile", "_change_scroll"):
        cast(Mock, getattr(tray, name)).assert_not_called()


def test_no_wrapper_menu_and_no_extra_nesting(qapp: QApplication, tray: TrayIcon) -> None:
    _admit_verified_software(tray, qapp)
    assert not hasattr(tray, "software_menu")
    assert "software_menu" not in tray.__dict__
    for menu in (tray.profile_menu, tray.scroll_menu):
        assert isinstance(menu, QMenu)
        assert menu.parent() is tray.menu
        for action in menu.actions():
            if action.isSeparator():
                continue
            assert action.menu() is None  # pyright: ignore[reportUnnecessaryComparison]
    root_submenus = {action.menu() for action in tray.menu.actions() if action.menu() is not None}  # pyright: ignore[reportUnnecessaryComparison]
    assert root_submenus == {
        tray.profile_menu,
        tray.scroll_menu,
        tray.onboard_menu,
        tray.device_mode.menu,
    }


def test_header_persists_across_refresh_offline_and_modes(
    qapp: QApplication, tray: TrayIcon
) -> None:
    _admit_verified_software(tray, qapp)
    assert tray.profile_menu.isEnabled()
    assert tray.scroll_menu.isEnabled()
    tray.model.mark_unreachable("offline")
    qapp.processEvents()
    assert tray.software_header.text() == "Software controls"
    assert not tray.software_header.isEnabled()
    assert tray.software_header.font().bold()
    assert not tray.profile_menu.isEnabled()
    assert not tray.scroll_menu.isEnabled()
    tray.model.apply_snapshot(
        ServiceSnapshotView(
            "available",
            2,
            "wired",
            None,
            desired_mode="firmware",
            observed_mode="firmware",
            mode_ready=True,
        )
    )
    qapp.processEvents()
    assert tray.software_header.text() == "Software controls"
    assert not tray.software_header.isEnabled()
    assert not tray.profile_menu.isEnabled()
    assert not tray.scroll_menu.isEnabled()
    assert tray.onboard_menu.isEnabled()
    _admit_verified_software(tray, qapp)
    assert tray.software_header.text() == "Software controls"
    assert tray.profile_menu.isEnabled()
    assert tray.scroll_menu.isEnabled()


@pytest.mark.parametrize(
    "setup",
    ["firmware", "offline", "calibration", "not-ready", "pending", "mismatch"],
)
def test_both_menus_gated_together(qapp: QApplication, tray: TrayIcon, setup: str) -> None:
    _admit_verified_software(tray, qapp)
    assert tray.profile_menu.isEnabled()
    assert tray.scroll_menu.isEnabled()
    if setup == "firmware":
        tray.model.apply_snapshot(
            ServiceSnapshotView(
                "available",
                2,
                "hyperspeed",
                None,
                desired_mode="firmware",
                observed_mode="firmware",
                mode_ready=True,
            )
        )
    elif setup == "offline":
        tray.model.mark_unreachable("offline")
    elif setup == "calibration":
        tray.model.apply_snapshot(
            ServiceSnapshotView(
                "available",
                2,
                "hyperspeed",
                None,
                desired_mode="software",
                observed_mode="software",
                mode_ready=True,
                calibrating=True,
            )
        )
    elif setup == "not-ready":
        tray.model.apply_snapshot(
            ServiceSnapshotView(
                "available",
                2,
                "hyperspeed",
                None,
                desired_mode="software",
                observed_mode="software",
                mode_ready=False,
            )
        )
    elif setup == "pending":
        tray.set_profile_switching(True)
    else:
        tray.model.apply_snapshot(
            ServiceSnapshotView(
                "available",
                2,
                "hyperspeed",
                None,
                desired_mode="firmware",
                observed_mode="software",
                mode_ready=True,
            )
        )
    qapp.processEvents()
    try:
        assert not tray.profile_menu.isEnabled()
        assert not tray.scroll_menu.isEnabled()
        assert tray.software_header.text() == "Software controls"
        assert not tray.software_header.isEnabled()
    finally:
        if setup == "pending":
            tray.set_profile_switching(False)
            qapp.processEvents()


def test_blocked_triggers_reconcile_without_mutations(qapp: QApplication, tray: TrayIcon) -> None:
    select = cast(Mock, tray._select_profile)  # pyright: ignore[reportPrivateUsage]
    scroll = cast(Mock, tray._change_scroll)  # pyright: ignore[reportPrivateUsage]
    _admit_verified_software(tray, qapp)
    assert tray.profile_menu.isEnabled()
    checked_before = [action.isChecked() for action in tray.scroll_actions.values()]
    tray.model.apply_snapshot(
        ServiceSnapshotView(
            "available",
            2,
            "hyperspeed",
            None,
            desired_mode="firmware",
            observed_mode="firmware",
            mode_ready=True,
        )
    )
    qapp.processEvents()
    assert not tray.profile_menu.isEnabled()
    assert not tray.scroll_menu.isEnabled()
    tray.scroll_actions["free_spin"].trigger()
    tray._scroll_requested(mode="free_spin")  # pyright: ignore[reportPrivateUsage]
    for action in (*tray.scroll_actions.values(), *tray.profile_actions.values()):
        action.setEnabled(True)
        action.trigger()
        action.setEnabled(False)
    tray._profile_requested("second")  # pyright: ignore[reportPrivateUsage]
    qapp.processEvents()
    select.assert_not_called()
    scroll.assert_not_called()
    assert [action.isChecked() for action in tray.scroll_actions.values()] == checked_before


def test_menu_open_model_change_updates_root_menus(qapp: QApplication, tray: TrayIcon) -> None:
    tray.model.apply_configuration(1, dump_toml(default_configuration()))
    tray.menu.show()
    tray.profile_menu.show()
    tray.scroll_menu.show()
    qapp.processEvents()
    _admit_verified_software(tray, qapp)
    assert tray.profile_menu.isEnabled()
    assert tray.scroll_menu.isEnabled()
    tray.model.apply_snapshot(
        ServiceSnapshotView(
            "available",
            2,
            "wired",
            None,
            desired_mode="firmware",
            observed_mode="firmware",
            mode_ready=True,
        )
    )
    qapp.processEvents()
    tray.menu.aboutToShow.emit()
    tray.profile_menu.aboutToShow.emit()
    tray.scroll_menu.aboutToShow.emit()
    qapp.processEvents()
    assert not tray.profile_menu.isEnabled()
    assert not tray.scroll_menu.isEnabled()
    assert tray.onboard_menu.isEnabled()
    tray.menu.hide()


def test_safety_gate_text_and_device_mode_offline(qapp: QApplication, tray: TrayIcon) -> None:
    assert MODE_SWITCH_GATE == "Switch mode (safety validation required)"
    assert tray.device_mode.gate_action.text() == MODE_SWITCH_GATE
    assert not tray.device_mode.gate_action.isEnabled()
    assert "held-output, wake, failure and reconnect" in tray.device_mode.gate_action.toolTip()
    assert "readiness is reported separately" in tray.device_mode.gate_action.toolTip()
    assert tray.device_mode.menu.isEnabled()
    assert tray.device_mode.remapping_action.text().endswith("(service offline)")
