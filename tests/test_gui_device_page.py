import os
from collections.abc import Iterator
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_support import FakeClient, make_presenter, sync_run
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QGroupBox, QLabel, QVBoxLayout, QWidget

from naga_control.config import parse_toml
from naga_control.gui.device_page import DevicePage
from naga_control.gui.models import ObservedView, ServiceSnapshotView
from naga_control.gui.overview_page import OverviewPage
from naga_control.gui.two_columns import TwoColumns


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    yield cast(QApplication, app)


def _page(qapp: QApplication) -> tuple[DevicePage, FakeClient]:
    presenter, model, client = make_presenter("")
    page = DevicePage(presenter, model, sync_run)
    sync_run(presenter.refresh)
    qapp.processEvents()
    return page, client


def _column(text: str) -> QWidget:
    column = QWidget()
    QVBoxLayout(column).addWidget(QLabel(text))
    return column


def test_columns_reflow_using_viewport_width_and_keep_contents_at_top(qapp: QApplication) -> None:
    left, right = _column("Left"), _column("Right")
    page = TwoColumns(left, right)
    page.resize(1100, 1000)
    page.show()
    qapp.processEvents()

    assert not page.is_stacked
    assert page.columns_layout.getItemPosition(page.columns_layout.indexOf(left)) == (0, 0, 1, 1)
    assert page.columns_layout.getItemPosition(page.columns_layout.indexOf(right)) == (0, 1, 1, 1)
    assert page.columns_layout.alignment() & Qt.AlignmentFlag.AlignTop
    assert left.y() == right.y()
    assert left.height() < 150
    assert right.height() < 150

    page.resize(640, 1000)
    qapp.processEvents()
    assert page.viewport().width() < 850
    assert page.is_stacked
    assert page.columns_layout.getItemPosition(page.columns_layout.indexOf(left)) == (0, 0, 1, 1)
    assert page.columns_layout.getItemPosition(page.columns_layout.indexOf(right)) == (1, 0, 1, 1)
    assert right.y() > left.y()
    assert right.y() + right.height() < 300

    page.resize(1100, 1000)
    qapp.processEvents()
    assert not page.is_stacked
    assert page.columns_layout.getItemPosition(page.columns_layout.indexOf(right)) == (0, 1, 1, 1)
    page.close()


def test_columns_scroll_when_stacked_content_exceeds_viewport(qapp: QApplication) -> None:
    left, right = _column("Left"), _column("Right")
    left.setMinimumHeight(400)
    right.setMinimumHeight(400)
    page = TwoColumns(left, right)
    page.resize(640, 300)
    page.show()
    qapp.processEvents()

    assert page.is_stacked
    assert page.verticalScrollBar().maximum() > 0
    assert page.horizontalScrollBar().maximum() == 0
    page.close()


def test_device_groups_and_only_selected_plate_selector(qapp: QApplication) -> None:
    page, _client = _page(qapp)
    page.resize(1100, 1000)
    page.show()
    qapp.processEvents()

    assert {group.title() for group in page.findChildren(QGroupBox)} == {
        "Connection and Battery",
        "Power",
        "Profiles",
        "Updates",
    }
    assert page.findChildren(QComboBox) == [page.profiles.plate_box]
    assert not hasattr(page.overview, "profiles_box")
    assert page.power.header_widget.isHidden()
    assert not page.power.profile_label.isVisible()
    assert page.power.apply_button.text() == "Apply power"
    assert page.profiles.list_widget.maximumHeight() == 220
    assert page.profiles.list_widget.height() <= 220
    assert not page.is_stacked

    page.resize(640, 1000)
    qapp.processEvents()
    assert page.is_stacked
    assert page.horizontalScrollBar().maximum() == 0
    page.close()


def test_power_applies_independently_and_device_delegates_discard(qapp: QApplication) -> None:
    page, client = _page(qapp)
    before = parse_toml(client.document)
    idle = before.profile(before.active_profile).power.idle_seconds
    assert not page.has_unsaved_changes()
    page.power.idle_spin.setValue(120 if idle != 120 else 180)
    assert page.has_unsaved_changes()

    page.discard_changes()
    assert page.power.idle_spin.value() == idle
    assert not page.has_unsaved_changes()
    assert not client.applied

    page.power.idle_spin.setValue(120 if idle != 120 else 180)
    page.power.apply_button.click()
    qapp.processEvents()
    after = parse_toml(client.document)
    assert len(client.applied) == 1
    assert after.profile(after.active_profile).power.idle_seconds == page.power.idle_spin.value()
    assert not page.has_unsaved_changes()


def test_device_delegates_power_guard_methods(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, _client = _page(qapp)
    dirty = Mock(return_value=True)
    discard = Mock()
    monkeypatch.setattr(page.power, "has_unsaved_changes", dirty)
    monkeypatch.setattr(page.power, "discard_changes", discard)
    assert page.has_unsaved_changes()
    page.discard_changes()
    dirty.assert_called_once_with()
    discard.assert_called_once_with()


def test_summary_keeps_errors_visible_while_diagnostics_collapse(qapp: QApplication) -> None:
    presenter, model, _client = make_presenter("")
    observed = ObservedView(
        dpi=(1600, 1800),
        active_dpi_stage=2,
        poll_rate=500,
        battery_percent=76,
        charging=True,
        firmware_version="v1.0",
        settings_failures=("logo write failed", "power write failed"),
    )
    model.apply_snapshot(
        ServiceSnapshotView("available", 9, "hyperspeed", "read failed", True, observed)
    )
    model.apply_configuration(7, "not read by overview")
    page = OverviewPage(presenter, model, sync_run)
    page.show()
    qapp.processEvents()

    assert page.connection_label.text() == "online"
    assert page.status_label.text() == "available"
    assert page.transport_label.text() == "hyperspeed"
    assert page.observed_dpi_label.text() == "1600x1800 (stage 2)"
    assert page.poll_rate_label.text() == "500 Hz"
    assert page.battery_label.text() == "76% charging"
    assert page.charging_label.text() == "yes"
    assert page.firmware_label.text() == "v1.0"
    assert page.error_label.isVisible()
    assert page.error_label.text() == "read failed"
    assert page.settings_failures_label.isVisible()
    assert page.settings_failures_label.text() == "logo write failed; power write failed"
    assert page.diagnostics_widget.isHidden()
    assert not page.refresh_button.isVisible()
    assert not page.generation_label.isVisible()

    page.diagnostics_button.click()
    qapp.processEvents()
    assert page.diagnostics_widget.isVisible()
    assert page.diagnostics_widget.isEnabled()
    assert page.generation_label.text() == "9"
    assert page.revision_label.text() == "7"
    assert page.calibrating_label.text() == "yes"
    assert page.refresh_button.isVisible()
    assert page.diagnostics_button.text() == "Hide diagnostics"
    page.diagnostics_button.click()
    qapp.processEvents()
    assert page.diagnostics_widget.isHidden()
    assert page.error_label.isVisible()
    page.close()


@pytest.mark.parametrize("charging", [True, False, None])
def test_charging_is_independent_of_battery_readback(
    qapp: QApplication, charging: bool | None
) -> None:
    presenter, model, _client = make_presenter("")
    page = OverviewPage(presenter, model, sync_run)
    model.apply_snapshot(
        ServiceSnapshotView("available", 1, "wired", None, observed=ObservedView(charging=charging))
    )
    qapp.processEvents()
    assert page.battery_label.text() == "unknown"
    assert page.charging_label.text() == {True: "yes", False: "no", None: "unknown"}[charging]


def test_overview_shows_firmware_mode_without_claiming_software_mapping(
    qapp: QApplication,
) -> None:
    presenter, model, _client = make_presenter("")
    page = OverviewPage(presenter, model, sync_run)
    model.apply_snapshot(
        ServiceSnapshotView(
            "available",
            1,
            "wired",
            None,
            desired_mode="firmware",
            observed_mode="firmware",
            mode_ready=True,
        )
    )
    qapp.processEvents()
    assert page.status_label.text() == "firmware (software mapping off)"
    assert page.mode_label.text() == "firmware (desired firmware)"
    assert not page.calibrate_button.isEnabled()

    model.apply_snapshot(
        ServiceSnapshotView(
            "unavailable",
            2,
            "wired",
            None,
            desired_mode="firmware",
            observed_mode="software",
            mode_error="driver reasserted",
        )
    )
    qapp.processEvents()
    assert page.mode_label.text() == "software (desired firmware)"
    assert page.mode_error_label.text() == "driver reasserted"
    page.close()


def test_diagnostics_actions_still_dispatch_through_presenter(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    presenter, model, _client = make_presenter("")
    refresh, release, begin, end = (AsyncMock() for _ in range(4))
    monkeypatch.setattr(presenter, "refresh", refresh)
    monkeypatch.setattr(presenter, "release_all", release)
    monkeypatch.setattr(presenter, "begin_calibration", begin)
    monkeypatch.setattr(presenter, "end_calibration", end)
    page = OverviewPage(presenter, model, sync_run)
    page.diagnostics_button.click()
    page.refresh_button.click()
    page.release_button.click()
    page.calibrate_button.click()
    model.apply_snapshot(ServiceSnapshotView("available", 1, "wired", None, True))
    qapp.processEvents()
    page.calibrate_button.click()

    refresh.assert_awaited_once_with()
    release.assert_awaited_once_with()
    begin.assert_awaited_once_with()
    end.assert_awaited_once_with()
