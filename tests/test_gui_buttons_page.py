import os
from collections.abc import Iterator
from typing import cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_buttons_fakes import FakeClient, opened, sync_run
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from naga_control.config import parse_toml
from naga_control.domain.actions import KeyAction, KeyComboAction, MouseButtonAction
from naga_control.domain.defaults import default_configuration
from naga_control.gui.buttons_page import ButtonsPage
from naga_control.gui.models import ServiceModel
from naga_control.gui.presenter import GuiPresenter


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    yield cast(QApplication, app)


def _page(qapp: QApplication) -> tuple[ButtonsPage, FakeClient]:
    client = FakeClient()
    model = ServiceModel()
    presenter = GuiPresenter(model, open_client=lambda: opened(client))
    page = ButtonsPage(presenter, model, sync_run)
    sync_run(presenter.refresh)
    qapp.processEvents()
    return page, client


def _row(page: ButtonsPage, control_id: str):
    for row in page.rows:
        if row.control_id == control_id:
            return row
    raise AssertionError(f"no row for {control_id}")


def test_page_lists_side_buttons_in_numeric_order_with_illustration_numbers(
    qapp: QApplication,
) -> None:
    page, _client = _page(qapp)

    controls = [row.control_id for row in page.rows]
    assert len(controls) == 7 + 12 + 6 + 2
    assert controls[:7] == [
        "dpi_up",
        "dpi_down",
        "wheel_tilt_left",
        "wheel_tilt_right",
        "top_front",
        "top_rear",
        "ring_finger",
    ]
    assert controls[7:19] == [f"side_12_{number}" for number in range(1, 13)]
    assert controls[19:25] == [f"side_6_{number}" for number in range(1, 7)]
    assert controls[25:] == ["side_2_front", "side_2_rear"]
    assert [int(row.number_label.text()) for row in page.rows] == [3, 4, *range(6, 31)]
    from naga_control.gui.mapping_zones import zone_for_control

    for row in page.rows:
        zone = zone_for_control(row.control_id)
        assert zone is not None
        assert int(row.number_label.text()) == zone.number
    assert page.rows_layout.count() == 31  # Header and all 30 illustration numbers.
    assert _row(page, "top_front").kind_box.currentText() == "passthrough"
    assert not _row(page, "top_front").detail_edit.isEnabled()
    assert not page.apply_button.isEnabled()


def test_changing_an_action_marks_the_page_dirty(qapp: QApplication) -> None:
    page, _client = _page(qapp)

    row = _row(page, "dpi_up")
    row.kind_box.setCurrentText("mouse_button")
    row.detail_edit.setCurrentText("forward")

    assert page.apply_button.isEnabled()
    assert page.status_label.text() == "unsaved changes"


def test_apply_sends_replacement_bindings(qapp: QApplication) -> None:
    page, client = _page(qapp)

    row = _row(page, "dpi_up")
    row.kind_box.setCurrentText("mouse_button")
    row.detail_edit.setCurrentText("forward")
    page.apply_button.click()
    qapp.processEvents()

    document = client.applied[0]
    configuration = parse_toml(document)
    profile = configuration.profile(configuration.active_profile)
    binding = profile.bindings.action_for("dpi_up", profile.plate_layout)
    assert binding == MouseButtonAction(button="forward")
    assert configuration.revision == default_configuration().revision + 1
    assert page.status_label.text() == "applied"
    assert not page.apply_button.isEnabled()


def test_invalid_combo_is_rejected_before_sending(qapp: QApplication) -> None:
    page, client = _page(qapp)

    row = _row(page, "top_front")
    row.kind_box.setCurrentText("key_combo")
    row.detail_edit.setCurrentText("single_key")
    page.apply_button.click()
    qapp.processEvents()

    assert client.applied == []
    assert page.status_label.text().startswith("rejected:")
    assert page.model.apply_status is not None


def test_record_key_and_shortcut_apply_through_existing_editor(qapp: QApplication) -> None:
    page, client = _page(qapp)
    page.show()
    qapp.processEvents()
    row = _row(page, "ring_finger")
    assert row.record_button.isVisible()

    row.record_button.click()
    QTest.keyClick(row.record_button, Qt.Key.Key_K)
    assert row.kind_box.currentText() == "key"
    assert row.detail_edit.currentText() == "k"
    assert page.apply_button.isEnabled()

    row.record_button.click()
    QTest.keyClick(
        row.record_button,
        Qt.Key.Key_T,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    assert row.kind_box.currentText() == "key_combo"
    assert row.detail_edit.currentText() == "left_ctrl+left_shift+t"
    page.apply_button.click()
    qapp.processEvents()

    configuration = parse_toml(client.applied[0])
    assert configuration.profile(configuration.active_profile).bindings.action_for(
        "ring_finger", 12
    ) == KeyComboAction(modifiers=("left_ctrl", "left_shift"), key="t")


def test_record_modifier_alone_and_switch_back_to_key(qapp: QApplication) -> None:
    page, client = _page(qapp)
    page.show()
    qapp.processEvents()
    row = _row(page, "top_front")
    row.kind_box.setCurrentText("key_combo")
    row.record_button.click()
    QTest.keyClick(row.record_button, Qt.Key.Key_Control)

    assert row.kind_box.currentText() == "key"
    assert row.detail_edit.currentText() == "left_ctrl"
    page.apply_button.click()
    qapp.processEvents()
    configuration = parse_toml(client.applied[0])
    assert configuration.profile(configuration.active_profile).bindings.action_for(
        "top_front", 12
    ) == KeyAction(key="left_ctrl")


@pytest.mark.parametrize(
    ("key", "scan", "expected"),
    [
        (Qt.Key.Key_Control, 105, "right_ctrl"),
        (Qt.Key.Key_Alt, 108, "right_alt"),
    ],
)
def test_record_right_modifier_applies_to_button(
    qapp: QApplication, key: Qt.Key, scan: int, expected: str
) -> None:
    page, client = _page(qapp)
    page.show()
    qapp.processEvents()
    row = _row(page, "ring_finger")
    row.record_button.click()
    modifier = (
        Qt.KeyboardModifier.ControlModifier
        if key == Qt.Key.Key_Control
        else Qt.KeyboardModifier.AltModifier
    )
    for event_type in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        qapp.sendEvent(row.record_button, QKeyEvent(event_type, key, modifier, scan, 0, 0, ""))

    assert row.detail_edit.currentText() == expected
    page.apply_button.click()
    qapp.processEvents()
    configuration = parse_toml(client.applied[0])
    assert configuration.profile(configuration.active_profile).bindings.action_for(
        "ring_finger", 12
    ) == KeyAction(expected)


def test_record_f12_for_ring_finger_applies_as_a_key(qapp: QApplication) -> None:
    page, client = _page(qapp)
    page.show()
    qapp.processEvents()
    row = _row(page, "ring_finger")
    row.record_button.click()
    QTest.keyClick(row.record_button, Qt.Key.Key_F12)

    assert row.detail_edit.currentText() == "f12"
    page.apply_button.click()
    qapp.processEvents()
    configuration = parse_toml(client.applied[0])
    assert configuration.profile(configuration.active_profile).bindings.action_for(
        "ring_finger", 12
    ) == KeyAction("f12")


def test_record_cancel_focus_loss_and_unsupported_key_keep_binding(qapp: QApplication) -> None:
    page, _client = _page(qapp)
    page.show()
    qapp.processEvents()
    row = _row(page, "ring_finger")
    original = row.detail_edit.currentText()

    row.record_button.click()
    QTest.keyClick(row.record_button, Qt.Key.Key_Escape)
    assert row.record_button.text() == "Record"
    row.record_button.click()
    QTest.keyClick(row.record_button, Qt.Key.Key_F13)
    assert row.record_button.text() == "Unsupported key"
    assert row.detail_edit.currentText() == original
    row.kind_box.setFocus()
    qapp.processEvents()
    assert row.record_button.text() == "Record"
    assert not page.apply_button.isEnabled()


def test_record_only_offered_for_keyboard_actions(qapp: QApplication) -> None:
    page, _client = _page(qapp)
    page.show()
    row = _row(page, "dpi_up")
    assert not row.record_button.isVisible()
    row.kind_box.setCurrentText("key")
    assert row.record_button.isVisible()
    row.kind_box.setCurrentText("mouse_button")
    assert not row.record_button.isVisible()


def test_repeated_applies_do_not_leave_orphan_labels(qapp: QApplication) -> None:
    page, client = _page(qapp)
    for button in ("forward", "back", "middle"):
        row = _row(page, "dpi_up")
        row.kind_box.setCurrentText("mouse_button")
        row.detail_edit.setCurrentText(button)
        page.apply_button.click()
        qapp.processEvents()
        assert page.rows_layout.count() == 31
        assert len(page.rows) == 27
        assert not page.apply_button.isEnabled()
    assert len(client.applied) == 3


def test_mapping_map_click_selects_the_binding_row(qapp: QApplication) -> None:
    from naga_control.gui.mapping_zones import zone_for_control

    page, _client = _page(qapp)
    zone = zone_for_control("dpi_up")
    assert zone is not None

    page.mapping_map.zone_clicked(zone)
    qapp.processEvents()

    selected = _row(page, "dpi_up")
    assert "rgba(68, 255, 136" in selected.root.styleSheet()


def test_mapping_map_renders_artwork_smoothly(qapp: QApplication) -> None:
    page, _client = _page(qapp)

    view = page.mapping_map
    assert view.pixmap_item.transformationMode() == Qt.TransformationMode.SmoothTransformation
    assert bool(view.renderHints() & QPainter.RenderHint.SmoothPixmapTransform)


def test_mapping_map_shows_current_bindings(qapp: QApplication) -> None:
    page, _client = _page(qapp)

    dpi_up = next(item for item in page.mapping_map.zone_items if item.zone.control_id == "dpi_up")
    assert dpi_up.toolTip().startswith("DPI up — ")


def test_editing_all_plates_preserves_runtime_layout(qapp: QApplication) -> None:
    from naga_control.gui.actions_view import action_for_control
    from naga_control.gui.mapping_zones import all_zones

    page, client = _page(qapp)
    for control in ("side_12_3", "side_6_6", "side_2_rear"):
        row = _row(page, control)
        row.kind_box.setCurrentText("mouse_button")
        row.detail_edit.setCurrentText("middle")
    page.apply_button.click()
    qapp.processEvents()

    configuration = parse_toml(client.document)
    profile = configuration.profile(configuration.active_profile)
    assert profile.plate_layout == 12
    for control in ("side_12_3", "side_6_6", "side_2_rear"):
        assert action_for_control(profile.bindings, control) == MouseButtonAction(button="middle")
        assert _row(page, control).detail_edit.currentText() == "middle"
    for zone in all_zones():
        if zone.control_id is not None:
            page.mapping_map.zone_clicked(zone)
            row = _row(page, zone.control_id)
            assert int(row.number_label.text()) == zone.number
            assert "rgba(68, 255, 136" in row.root.styleSheet()
