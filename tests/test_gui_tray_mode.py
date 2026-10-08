"""Offscreen read-only mode menu tests; no live GUI, IPC or hardware."""

import os
from collections.abc import Iterator
from dataclasses import replace
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_support import opened, sync_run
from gui_tray_scroll_fakes import ScrollClient
from PySide6.QtWidgets import QApplication

from naga_control.config import dump_toml, parse_toml
from naga_control.gui.models import ServiceModel, ServiceSnapshotView, parse_snapshot
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


def test_persistent_mode_submenu_is_accessible_offline_and_explains_gate(
    qapp: QApplication, tray: TrayIcon
) -> None:
    mode = tray.device_mode
    assert mode.menu.title() == "Device mode"
    assert mode.menu.menuAction() in tray.menu.actions()
    assert tray.software_header in tray.menu.actions()
    assert not hasattr(tray, "software_menu")
    assert tray.onboard_menu.menuAction() in tray.menu.actions()
    assert tray.profile_menu.menuAction() in tray.menu.actions()
    assert tray.scroll_menu.menuAction() in tray.menu.actions()
    assert tray.profile_menu.parent() is tray.menu
    assert tray.scroll_menu.parent() is tray.menu
    assert mode.menu.isEnabled()
    assert mode.menu.menuAction().isEnabled()
    assert mode.menu is not tray.scroll_menu
    assert not tray.scroll_menu.isEnabled()
    assert not tray.profile_menu.isEnabled()
    assert not tray.onboard_menu.isEnabled()
    assert mode.requested_action.text() == "Requested: Unknown"
    assert mode.observed_action.text() == "Observed: Unknown (service offline)"
    assert mode.remapping_action.text() == "Software remapping: Unknown (service offline)"
    assert mode.gate_action.isVisible()
    assert mode.gate_action.text() == "Switch mode (safety validation required)"
    assert not mode.gate_action.isEnabled()
    assert "held-output, wake, failure and reconnect" in mode.gate_action.toolTip()
    assert "readiness is reported separately" in mode.gate_action.toolTip()
    assert "not the selected software profile" in mode.menu.menuAction().toolTip()
    tray.menu.aboutToShow.emit()
    mode.menu.aboutToShow.emit()
    qapp.processEvents()
    assert tray.device_mode is mode
    assert all(
        not action.isCheckable() and not action.isEnabled() for action in mode.menu.actions()
    )


@pytest.mark.parametrize(
    ("desired", "observed", "ready", "calibrating", "error", "status", "expected"),
    [
        ("software", "software", True, False, None, "available", "Active (software mode verified)"),
        ("firmware", "firmware", True, False, None, "available", "Off (onboard mode verified)"),
        (
            "firmware",
            "software",
            True,
            False,
            None,
            "available",
            "Not ready (requested/observed differ)",
        ),
        (
            "software",
            "firmware",
            True,
            False,
            None,
            "available",
            "Not ready (requested/observed differ)",
        ),
        ("software", "software", False, False, None, "available", "Not ready"),
        ("firmware", "firmware", False, False, None, "available", "Not ready"),
        ("software", None, True, False, None, "available", "Unknown (mode not verified)"),
        (None, None, False, False, None, "available", "Unknown (mode not verified)"),
        ("software", "unexpected", True, False, None, "available", "Unknown (mode not verified)"),
        ("software", "software", True, True, None, "available", "Off (calibration passthrough)"),
        ("software", "software", True, False, "timeout", "available", "Not ready (mode error)"),
        (
            "firmware",
            "firmware",
            True,
            False,
            None,
            "unavailable",
            "Not ready (device unavailable)",
        ),
    ],
)
def test_mode_states_refresh_in_place_without_false_success(
    qapp: QApplication,
    tray: TrayIcon,
    desired: str | None,
    observed: str | None,
    ready: bool,
    calibrating: bool,
    error: str | None,
    status: str,
    expected: str,
) -> None:
    mode = tray.device_mode
    actions = mode.menu.actions()
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
    labels = {"software": "Software / driver", "firmware": "Onboard / firmware"}
    assert mode.requested_action.text() == f"Requested: {labels.get(desired or '', 'Unknown')}"
    assert mode.observed_action.text() == f"Observed: {labels.get(observed or '', 'Unknown')}"
    assert mode.remapping_action.text() == f"Software remapping: {expected}"
    assert mode.error_action.isVisible() == (error is not None)
    if error:
        assert mode.error_action.text() == "Mode error: timeout"
    assert mode.menu.actions() == actions
    assert mode.menu.isEnabled()
    assert mode.gate_action.isVisible()


@pytest.mark.parametrize("requested", ["software", "firmware"])
def test_retained_snapshot_loses_current_claims_on_disconnect_and_recovers(
    qapp: QApplication, tray: TrayIcon, requested: str
) -> None:
    snapshot = ServiceSnapshotView(
        "available",
        1,
        "hyperspeed",
        None,
        desired_mode=requested,
        observed_mode=requested,
        mode_ready=True,
        mode_error="old error",
    )
    tray.model.apply_snapshot(snapshot)
    qapp.processEvents()
    tray.model.mark_unreachable("lost")
    qapp.processEvents()
    mode = tray.device_mode
    assert mode.menu.isEnabled()
    assert "last known; offline" in mode.requested_action.text()
    assert mode.observed_action.text() == "Observed: Unknown (service offline)"
    assert mode.remapping_action.text() == "Software remapping: Unknown (service offline)"
    assert mode.error_action.text() == "Mode error: Last known (offline): old error"
    tray.model.apply_snapshot(replace(snapshot, mode_error=None))
    qapp.processEvents()
    assert "offline" not in mode.requested_action.text()
    assert "verified" in mode.remapping_action.text()
    assert not mode.error_action.isVisible()


def test_remote_refresh_and_all_programmatic_mode_triggers_have_zero_mutations(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tray: TrayIcon
) -> None:
    client = ScrollClient()
    mutations = [AsyncMock() for _ in range(5)]
    for name, mock in zip(
        (
            "apply_configuration",
            "select_profile",
            "begin_calibration",
            "end_calibration",
            "release_all",
        ),
        mutations,
        strict=True,
    ):
        monkeypatch.setattr(client, name, mock)
    presenter = GuiPresenter(tray.model, open_client=lambda: opened(client))
    sync_run(presenter.refresh)
    qapp.processEvents()
    mode = tray.device_mode
    assert mode.requested_action.text() == "Requested: Software / driver"
    assert mode.remapping_action.text() == "Software remapping: Active (software mode verified)"
    assert tray.profile_menu.isEnabled()
    assert tray.scroll_menu.isEnabled()
    assert not tray.onboard_menu.isEnabled()
    config = parse_toml(client.document)
    client.document = dump_toml(replace(config, revision=config.revision + 1, mode="firmware"))
    client.snapshot.update(desired_mode="firmware", observed_mode="firmware", mode_ready=True)
    sync_run(presenter.refresh)
    qapp.processEvents()
    assert mode.requested_action.text() == "Requested: Onboard / firmware"
    assert mode.observed_action.text() == "Observed: Onboard / firmware"
    assert mode.remapping_action.text() == "Software remapping: Off (onboard mode verified)"
    # Firmware verification greys software controls; onboard stays readable.
    assert not tray.profile_menu.isEnabled()
    assert not tray.scroll_menu.isEnabled()
    assert tray.onboard_menu.isEnabled()
    before = client.document
    for offline in (False, True):
        if offline:
            tray.model.mark_unreachable("offline")
        tray.menu.aboutToShow.emit()
        mode.menu.aboutToShow.emit()
        for action in (mode.menu.menuAction(), *mode.menu.actions()):
            action.trigger()
        # Even artificially enabled read-only QActions have no mutation callbacks.
        for action in mode.menu.actions():
            action.setEnabled(True)
            action.trigger()
            action.setEnabled(False)
        qapp.processEvents()
    for mock in mutations:
        mock.assert_not_called()
    assert client.applied == []
    assert client.document == before
    assert tray.model.apply_status is None
    for callback in ("_toggle_window", "_select_profile", "_change_scroll"):
        cast(Mock, getattr(tray, callback)).assert_not_called()


def test_legacy_snapshot_menu_never_invents_mode_readiness(
    qapp: QApplication, tray: TrayIcon
) -> None:
    tray.model.apply_snapshot(parse_snapshot('{"status":"available","generation":1}'))
    qapp.processEvents()
    assert tray.device_mode.requested_action.text() == "Requested: Unknown"
    assert tray.device_mode.observed_action.text() == "Observed: Unknown"
    assert (
        tray.device_mode.remapping_action.text()
        == "Software remapping: Unknown (mode not verified)"
    )
