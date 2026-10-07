"""Button row widgets for the buttons page."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

from naga_control.domain.actions import DEVICE_ACTIONS, MOUSE_BUTTONS, Action
from naga_control.gui.actions_view import (
    ACTION_KINDS,
    action_kind,
    control_display_name,
    format_action_detail,
)
from naga_control.gui.click_wheel_combo import ClickWheelComboBox
from naga_control.gui.key_recorder import KeyRecorder


@dataclass
class ButtonRow:
    root: QWidget
    control_id: str
    kind_box: QComboBox
    detail_edit: QComboBox
    record_button: KeyRecorder
    number_label: QLabel

    def selected_kind(self) -> str:
        return self.kind_box.currentText()

    def selected_detail(self) -> str:
        return self.detail_edit.currentText().strip()


def sync_detail_options(row: ButtonRow, action: Action | None = None) -> None:
    kind = row.selected_kind()
    if action is not None and action_kind(action) == kind:
        items = [format_action_detail(action)]
    elif kind == "mouse_button":
        items = sorted(MOUSE_BUTTONS)
    elif kind == "device":
        items = sorted(DEVICE_ACTIONS)
    else:
        items = [format_action_detail(action)] if action is not None else [""]
    row.detail_edit.blockSignals(True)
    try:
        row.detail_edit.clear()
        row.detail_edit.addItems(items)
        if action is not None:
            row.detail_edit.setCurrentText(format_action_detail(action))
    finally:
        row.detail_edit.blockSignals(False)
    row.detail_edit.setEnabled(kind not in ("disabled", "passthrough"))
    row.record_button.setVisible(kind in ("key", "key_combo"))


def build_button_row(
    control: str,
    action: Action | None,
    number: int,
    label: str,
    *,
    on_kind_changed: Callable[[ButtonRow, str], None],
    on_detail_changed: Callable[[str], None],
    on_recorded: Callable[[ButtonRow, str, str], None],
) -> ButtonRow:
    kind_box = ClickWheelComboBox()
    kind_box.addItems(ACTION_KINDS)
    kind_box.setCurrentText(action_kind(action) if action is not None else "passthrough")
    detail_edit = ClickWheelComboBox()
    detail_edit.setEditable(True)
    detail_edit.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    record_button = KeyRecorder()
    row = QHBoxLayout()
    row.setContentsMargins(4, 2, 4, 2)
    number_label = QLabel(str(number))
    number_label.setFixedWidth(32)
    name_label = QLabel(label)
    name_label.setFixedWidth(100)
    name_label.setToolTip(control_display_name(control))
    row.addWidget(number_label)
    row.addWidget(name_label)
    kind_box.setMinimumWidth(0)
    detail_edit.setMinimumWidth(0)
    kind_box.setMinimumContentsLength(6)
    detail_edit.setMinimumContentsLength(6)
    kind_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    detail_edit.setSizeAdjustPolicy(
        QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
    )
    row.addWidget(kind_box, 1)
    row.addWidget(detail_edit, 1)
    row.addWidget(record_button)
    root = QWidget()
    root.setLayout(row)
    button_row = ButtonRow(
        root=root,
        control_id=control,
        kind_box=kind_box,
        detail_edit=detail_edit,
        record_button=record_button,
        number_label=number_label,
    )
    kind_box.currentTextChanged.connect(partial(on_kind_changed, button_row))
    detail_edit.currentTextChanged.connect(on_detail_changed)
    record_button.recorded.connect(partial(on_recorded, button_row))
    sync_detail_options(button_row, action)
    return button_row
