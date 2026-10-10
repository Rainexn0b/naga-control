import os
from collections.abc import Iterator
from typing import cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_buttons_fakes import FakeClient, opened, sync_run
from PySide6.QtWidgets import QApplication

from naga_control.config import parse_toml
from naga_control.domain.actions import KeyAction, KeyComboAction
from naga_control.gui.actions_view import control_display_name
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


def test_manual_chord_infers_selector_and_applies(qapp: QApplication) -> None:
    page, client = _page(qapp)
    row = _row(page, "top_front")
    row.kind_box.setCurrentText("key")
    row.detail_edit.setCurrentText("left_ctrl+left_shift+8")
    qapp.processEvents()
    line_edit = row.detail_edit.lineEdit()
    assert line_edit is not None
    line_edit.editingFinished.emit()
    qapp.processEvents()

    assert row.kind_box.currentText() == "key_combo"
    assert row.detail_edit.currentText() == "left_ctrl+left_shift+8"
    page.apply_button.click()
    qapp.processEvents()

    assert client.applied != []
    configuration = parse_toml(client.applied[0])
    binding = configuration.profile(configuration.active_profile).bindings.action_for(
        "top_front",
        12,  # type: ignore[arg-type]
    )
    assert binding == KeyComboAction(modifiers=("left_ctrl", "left_shift"), key="8")
    assert page.status_label.text() == "applied"


def test_manual_chord_with_tab_infers_and_applies(qapp: QApplication) -> None:
    page, client = _page(qapp)
    row = _row(page, "top_front")
    row.kind_box.setCurrentText("key")
    row.detail_edit.setCurrentText("left_ctrl+left_shift+tab")
    qapp.processEvents()
    line_edit = row.detail_edit.lineEdit()
    assert line_edit is not None
    line_edit.editingFinished.emit()
    qapp.processEvents()

    assert row.kind_box.currentText() == "key_combo"
    assert row.detail_edit.currentText() == "left_ctrl+left_shift+tab"
    page.apply_button.click()
    qapp.processEvents()

    configuration = parse_toml(client.applied[0])
    binding = configuration.profile(configuration.active_profile).bindings.action_for(
        "top_front",
        12,  # type: ignore[arg-type]
    )
    assert binding == KeyComboAction(modifiers=("left_ctrl", "left_shift"), key="tab")


def test_apply_without_editing_signal_still_infers(qapp: QApplication) -> None:
    page, client = _page(qapp)
    row = _row(page, "top_front")
    row.kind_box.setCurrentText("key")
    row.detail_edit.setCurrentText("left_ctrl+left_shift+8")
    qapp.processEvents()

    # No editingFinished: the selector has not synced yet.
    assert row.kind_box.currentText() == "key"
    page.apply_button.click()
    qapp.processEvents()

    configuration = parse_toml(client.applied[0])
    binding = configuration.profile(configuration.active_profile).bindings.action_for(
        "top_front",
        12,  # type: ignore[arg-type]
    )
    assert binding == KeyComboAction(modifiers=("left_ctrl", "left_shift"), key="8")


def test_literal_equal_saves_without_kind_switch(qapp: QApplication) -> None:
    page, client = _page(qapp)
    row = _row(page, "top_front")
    row.kind_box.setCurrentText("key")
    row.detail_edit.setCurrentText("=")
    qapp.processEvents()
    line_edit = row.detail_edit.lineEdit()
    assert line_edit is not None
    line_edit.editingFinished.emit()
    qapp.processEvents()

    assert row.kind_box.currentText() == "key"
    assert row.detail_edit.currentText() == "equal"
    page.apply_button.click()
    qapp.processEvents()

    configuration = parse_toml(client.applied[0])
    binding = configuration.profile(configuration.active_profile).bindings.action_for(
        "top_front",
        12,  # type: ignore[arg-type]
    )
    assert binding == KeyAction(key="equal")


def test_literal_minus_saves_without_kind_switch(qapp: QApplication) -> None:
    page, client = _page(qapp)
    row = _row(page, "top_front")
    row.kind_box.setCurrentText("key")
    row.detail_edit.setCurrentText("-")
    qapp.processEvents()
    line_edit = row.detail_edit.lineEdit()
    assert line_edit is not None
    line_edit.editingFinished.emit()
    qapp.processEvents()

    assert row.kind_box.currentText() == "key"
    assert row.detail_edit.currentText() == "minus"
    page.apply_button.click()
    qapp.processEvents()

    configuration = parse_toml(client.applied[0])
    binding = configuration.profile(configuration.active_profile).bindings.action_for(
        "top_front",
        12,  # type: ignore[arg-type]
    )
    assert binding == KeyAction(key="minus")


@pytest.mark.parametrize(
    "invalid",
    ["left_ctrl+left_shift", "left_ctrl+", "not_a_modifier+t"],
)
def test_invalid_chord_rejected_with_row_info(qapp: QApplication, invalid: str) -> None:
    page, client = _page(qapp)
    bad = _row(page, "top_front")
    bad.kind_box.setCurrentText("key")
    bad.detail_edit.setCurrentText(invalid)
    good = _row(page, "top_rear")
    good.kind_box.setCurrentText("mouse_button")
    good.detail_edit.setCurrentText("middle")
    qapp.processEvents()
    line_edit = bad.detail_edit.lineEdit()
    assert line_edit is not None
    line_edit.editingFinished.emit()
    qapp.processEvents()

    # Invalid input never silently becomes a different action.
    assert bad.kind_box.currentText() == "key"
    page.apply_button.click()
    qapp.processEvents()

    assert client.applied == []
    status = page.status_label.text()
    assert status.startswith("rejected:")
    display = control_display_name("top_front")
    assert display in status
    assert "top_front" in status
    assert invalid in status
    assert "lowercase" in status or "modifier" in status
    # The offending row is highlighted and other edits survive intact.
    assert "rgba(68, 255, 136" in bad.root.styleSheet()
    assert good.detail_edit.currentText() == "middle"
    assert good.kind_box.currentText() == "mouse_button"
    assert page.has_unsaved_changes()


def test_non_key_kinds_untouched_by_editing_finished(qapp: QApplication) -> None:
    page, _client = _page(qapp)
    row = _row(page, "dpi_up")
    assert row.kind_box.currentText() == "device"
    line_edit = row.detail_edit.lineEdit()
    assert line_edit is not None
    line_edit.editingFinished.emit()
    qapp.processEvents()
    assert row.kind_box.currentText() == "device"

    mouse = _row(page, "top_front")
    mouse.kind_box.setCurrentText("mouse_button")
    mouse.detail_edit.setCurrentText("middle")
    qapp.processEvents()
    mouse_line = mouse.detail_edit.lineEdit()
    assert mouse_line is not None
    mouse_line.editingFinished.emit()
    qapp.processEvents()
    assert mouse.kind_box.currentText() == "mouse_button"
    assert mouse.detail_edit.currentText() == "middle"


def test_recorded_and_manual_entry_yield_equivalent(qapp: QApplication) -> None:
    recorded_page, recorded_client = _page(qapp)
    recorded_row = _row(recorded_page, "top_front")
    recorded_row.kind_box.setCurrentText("key")
    recorded_row.record_button.recorded.emit("key_combo", "left_ctrl+8")
    qapp.processEvents()
    assert recorded_row.kind_box.currentText() == "key_combo"
    assert recorded_row.detail_edit.currentText() == "left_ctrl+8"
    recorded_page.apply_button.click()
    qapp.processEvents()
    recorded_binding = (
        parse_toml(recorded_client.applied[0])
        .profile("default")
        .bindings.action_for(
            "top_front",
            12,  # type: ignore[arg-type]
        )
    )

    manual_page, manual_client = _page(qapp)
    manual_row = _row(manual_page, "top_front")
    manual_row.kind_box.setCurrentText("key")
    manual_row.detail_edit.setCurrentText("left_ctrl+8")
    qapp.processEvents()
    manual_line = manual_row.detail_edit.lineEdit()
    assert manual_line is not None
    manual_line.editingFinished.emit()
    qapp.processEvents()
    assert manual_row.kind_box.currentText() == "key_combo"
    assert manual_row.detail_edit.currentText() == "left_ctrl+8"
    manual_page.apply_button.click()
    qapp.processEvents()
    manual_binding = (
        parse_toml(manual_client.applied[0])
        .profile("default")
        .bindings.action_for(
            "top_front",
            12,  # type: ignore[arg-type]
        )
    )

    expected = KeyComboAction(modifiers=("left_ctrl",), key="8")
    assert recorded_binding == expected
    assert manual_binding == expected
    assert recorded_binding == manual_binding
