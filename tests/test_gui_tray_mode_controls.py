"""Tray software/onboard split, verified greying, and blocked-trigger safety."""

import os
from collections.abc import Iterator
from typing import cast
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_support import opened, sync_run
from gui_tray_scroll_fakes import ScrollClient
from PySide6.QtWidgets import QApplication

from naga_control.config import parse_toml
from naga_control.gui.models import ServiceModel, ServiceSnapshotView
from naga_control.gui.presenter import GuiPresenter
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


def _verified(model: ServiceModel, mode: str, qapp: QApplication) -> None:
    model.apply_snapshot(
        ServiceSnapshotView(
            "available",
            1,
            "hyperspeed",
            None,
            desired_mode=mode,
            observed_mode=mode,
            mode_ready=True,
        )
    )
    qapp.processEvents()


def test_split_groups_and_device_mode_discoverable(qapp: QApplication, tray: TrayIcon) -> None:
    assert tray.software_menu.title() == "Software controls"
    assert tray.onboard_menu.title() == "Onboard / firmware"
    assert tray.device_mode.menu.title() == "Device mode"
    assert tray.profile_menu.menuAction() in tray.software_menu.actions()
    assert tray.scroll_menu.menuAction() in tray.software_menu.actions()
    assert tray.software_menu.menuAction() in tray.menu.actions()
    assert tray.onboard_menu.menuAction() in tray.menu.actions()
    assert tray.device_mode.menu.menuAction() in tray.menu.actions()
    assert tray.device_mode.menu.isEnabled()
    assert tray.onboard_status_action.text() == "Uses mouse native behavior"
    assert tray.onboard_note_action.text() == "No onboard editing supported"
    assert not tray.onboard_status_action.isEnabled()
    assert not tray.onboard_note_action.isEnabled()


def test_neutral_gate_never_enables_and_keeps_safety_help(
    qapp: QApplication, tray: TrayIcon
) -> None:
    gate = tray.device_mode.gate_action
    assert gate.text() == "Switch mode (unavailable)"
    assert not gate.isEnabled()
    assert "held-output, wake, failure and reconnect" in gate.toolTip()
    gate.setEnabled(True)
    gate.trigger()
    qapp.processEvents()
    for name in ("_toggle_window", "_select_profile", "_change_scroll"):
        cast(Mock, getattr(tray, name)).assert_not_called()
    assert not tray.model.snapshot


@pytest.mark.parametrize(
    ("desired", "observed", "ready", "error", "calibrating", "status"),
    [
        (None, None, False, None, False, "available"),
        ("software", None, True, None, False, "available"),
        ("software", "firmware", True, None, False, "available"),
        ("software", "software", False, None, False, "available"),
        ("software", "software", True, "boom", False, "available"),
        ("software", "software", True, None, True, "available"),
        ("software", "software", True, None, False, "unavailable"),
    ],
)
def test_software_greyed_unless_verified(
    qapp: QApplication,
    tray: TrayIcon,
    desired: str | None,
    observed: str | None,
    ready: bool,
    error: str | None,
    calibrating: bool,
    status: str,
) -> None:
    from naga_control.config import dump_toml
    from naga_control.domain.defaults import default_configuration

    tray.model.apply_configuration(1, dump_toml(default_configuration()))
    _verified(tray.model, "software", qapp)
    qapp.processEvents()
    assert tray.software_menu.isEnabled()
    assert tray.profile_menu.isEnabled()
    assert tray.scroll_menu.isEnabled()
    tray.model.apply_snapshot(
        ServiceSnapshotView(
            status,
            1,
            "wired",
            None,
            calibrating=calibrating,
            desired_mode=desired,
            observed_mode=observed,
            mode_ready=ready,
            mode_error=error,
        )
    )
    qapp.processEvents()
    assert not tray.software_menu.isEnabled()
    assert not tray.profile_menu.isEnabled()
    assert not tray.scroll_menu.isEnabled()


def test_saved_firmware_policy_conflicts_with_verified_software_snapshot(
    qapp: QApplication, tray: TrayIcon
) -> None:
    from dataclasses import replace

    from naga_control.config import dump_toml, parse_toml
    from naga_control.domain.defaults import default_configuration

    base = default_configuration()
    firmware_doc = dump_toml(replace(base, mode="firmware"))
    tray.model.apply_configuration(1, firmware_doc)
    assert parse_toml(firmware_doc).mode == "firmware"
    _verified(tray.model, "software", qapp)
    qapp.processEvents()
    assert not tray.software_menu.isEnabled()
    assert not tray.profile_menu.isEnabled()
    assert not tray.scroll_menu.isEnabled()
    assert not tray.onboard_menu.isEnabled()


def test_verified_software_enables_only_software_group(qapp: QApplication, tray: TrayIcon) -> None:
    from naga_control.config import dump_toml
    from naga_control.domain.defaults import default_configuration

    tray.model.apply_configuration(1, dump_toml(default_configuration()))
    _verified(tray.model, "software", qapp)
    qapp.processEvents()
    assert tray.software_menu.isEnabled()
    assert tray.profile_menu.isEnabled()
    assert tray.scroll_menu.isEnabled()
    assert not tray.onboard_menu.isEnabled()


def test_verified_firmware_enables_only_onboard_group(qapp: QApplication, tray: TrayIcon) -> None:
    _verified(tray.model, "firmware", qapp)
    assert not tray.software_menu.isEnabled()
    assert not tray.profile_menu.isEnabled()
    assert not tray.scroll_menu.isEnabled()
    assert tray.onboard_menu.isEnabled()
    tray.onboard_status_action.trigger()
    tray.onboard_note_action.trigger()
    qapp.processEvents()
    for name in ("_toggle_window", "_select_profile", "_change_scroll"):
        cast(Mock, getattr(tray, name)).assert_not_called()


@pytest.mark.parametrize("variant", ["offline", "firmware", "mismatch", "not-ready"])
def test_blocked_triggers_reconcile_without_mutations(qapp: QApplication, variant: str) -> None:
    client = ScrollClient()
    select, scroll = Mock(), Mock()
    tray = TrayIcon(
        ServiceModel(),
        toggle_window=Mock(),
        select_profile=select,
        change_scroll=scroll,
        quit_app=Mock(),
    )
    presenter = GuiPresenter(tray.model, open_client=lambda: opened(client))
    sync_run(presenter.refresh)
    qapp.processEvents()
    assert tray.software_menu.isEnabled()
    if variant == "offline":
        tray.model.mark_unreachable("offline")
    elif variant == "firmware":
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
    elif variant == "mismatch":
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
    else:
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
    qapp.processEvents()
    assert not tray.software_menu.isEnabled()
    checked_before = [a.isChecked() for a in tray.scroll_actions.values()]
    profile_before = [a.isChecked() for a in tray.profile_actions.values()]
    tray.scroll_actions["free_spin"].trigger()
    tray._scroll_requested(mode="free_spin")  # pyright: ignore[reportPrivateUsage]
    for action in (*tray.scroll_actions.values(), *tray.profile_actions.values()):
        action.setEnabled(True)
        action.trigger()
        action.setEnabled(False)
    tray._profile_requested("second")  # pyright: ignore[reportPrivateUsage]
    tray._profile_requested("removed-stale-id")  # pyright: ignore[reportPrivateUsage]
    qapp.processEvents()
    select.assert_not_called()
    scroll.assert_not_called()
    assert [a.isChecked() for a in tray.scroll_actions.values()] == checked_before
    assert [a.isChecked() for a in tray.profile_actions.values()] == profile_before
    assert parse_toml(client.document).profile("first").scroll.mode == "tactile"
    tray.deleteLater()
    qapp.processEvents()


def test_snapshot_while_open_updates_enabling(qapp: QApplication, tray: TrayIcon) -> None:
    from naga_control.config import dump_toml
    from naga_control.domain.defaults import default_configuration

    tray.model.apply_configuration(1, dump_toml(default_configuration()))
    tray.software_menu.show()
    tray.scroll_menu.show()
    qapp.processEvents()
    _verified(tray.model, "software", qapp)
    assert tray.software_menu.isEnabled()
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
    assert not tray.software_menu.isEnabled()
    assert tray.onboard_menu.isEnabled()
    tray.software_menu.hide()
