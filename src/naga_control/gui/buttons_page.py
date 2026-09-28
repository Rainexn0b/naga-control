"""Buttons page: edit control bindings of the active profile and apply them."""

from dataclasses import dataclass
from functools import partial
from typing import cast

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from naga_control.config import parse_toml
from naga_control.domain.actions import DEVICE_ACTIONS, MOUSE_BUTTONS, Action
from naga_control.domain.errors import ConfigValidationError
from naga_control.domain.profiles import Configuration, LogicalControlId
from naga_control.gui.actions_view import (
    ACTION_KINDS,
    action_kind,
    control_display_name,
    controls_for_layout,
    format_action_detail,
    parse_action,
)
from naga_control.gui.editors import set_bindings, set_plate_layout
from naga_control.gui.models import ServiceModel
from naga_control.gui.presenter import ApplyOutcome, GuiPresenter
from naga_control.gui.worker import Runner

_OUTCOME_TEXT = {
    ApplyOutcome.APPLIED: "applied",
    ApplyOutcome.STALE: "changed on the service; reloaded, apply again",
    ApplyOutcome.INVALID: "rejected: invalid values",
    ApplyOutcome.UNREACHABLE: "service unreachable",
}

_PLATE_CHOICES: tuple[tuple[str, int], ...] = (
    ("12-button", 12),
    ("6-button", 6),
    ("2-button", 2),
)


@dataclass
class ButtonRow:
    root: QWidget
    control_id: str
    kind_box: QComboBox
    detail_edit: QComboBox

    def selected_kind(self) -> str:
        return self.kind_box.currentText()

    def selected_detail(self) -> str:
        return self.detail_edit.currentText().strip()


class ButtonsPage(QWidget):
    """Binding editor for the active profile with revision-checked apply."""

    model_changed = Signal()

    def __init__(self, presenter: GuiPresenter, model: ServiceModel, run: Runner) -> None:
        super().__init__()
        self.presenter = presenter
        self.model = model
        self._run = run
        self.rows: list[ButtonRow] = []
        self._loaded_actions: dict[str, Action | None] = {}
        self._loaded_document: str | None = None
        self._loaded_plate: int = 12

        self.model.add_listener(self.model_changed.emit)
        self.model_changed.connect(self._on_model_changed, Qt.ConnectionType.QueuedConnection)

        self.profile_label = QLabel("unknown profile")
        self.plate_box = QComboBox()
        for label, layout in _PLATE_CHOICES:
            self.plate_box.addItem(label, layout)
        self.plate_box.currentIndexChanged.connect(self._plate_changed)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.apply_button = QPushButton("Apply")
        self.apply_button.setEnabled(False)

        self.rows_area = QWidget()
        self.rows_layout = QFormLayout(self.rows_area)
        scroll = QScrollArea()
        scroll.setWidget(self.rows_area)
        scroll.setWidgetResizable(True)

        header = QFormLayout()
        header.addRow("Profile", self.profile_label)
        header.addRow("Side plate", self.plate_box)
        actions = QHBoxLayout()
        actions.addWidget(self.apply_button)
        column = QVBoxLayout()
        column.addLayout(header)
        column.addWidget(scroll)
        column.addLayout(actions)
        column.addWidget(self.status_label)
        self.setLayout(column)

        self.apply_button.clicked.connect(self._apply)
        self._on_model_changed()

    def _on_model_changed(self) -> None:
        self.status_label.setText(self.model.apply_status or "")
        document = self.model.configuration_document
        if document is None:
            return
        try:
            configuration = parse_toml(document)
        except ConfigValidationError:
            self.status_label.setText("service configuration is unreadable")
            return
        self.profile_label.setText(configuration.active_profile)
        if document != self._loaded_document:
            self._loaded_document = document
            self._load(configuration)

    def _load(self, configuration: Configuration, plate_layout: int | None = None) -> None:
        profile = configuration.profile(configuration.active_profile)
        layout = profile.plate_layout if plate_layout is None else plate_layout
        self.plate_box.blockSignals(True)
        index = [choice for _, choice in _PLATE_CHOICES].index(layout)
        self.plate_box.setCurrentIndex(index)
        self.plate_box.blockSignals(False)
        self._loaded_plate = profile.plate_layout
        self._loaded_actions = {}
        for row in self.rows:
            row.root.deleteLater()
        self.rows = []
        for control in controls_for_layout(layout):
            action = profile.bindings.action_for(control, profile.plate_layout)
            self._loaded_actions[control] = action
            self.rows.append(self._build_row(control, action))
            self.rows_layout.addRow(control_display_name(control), self.rows[-1].root)
        self._update_dirty()

    def _build_row(self, control: str, action: Action | None) -> ButtonRow:
        kind_box = QComboBox()
        kind_box.addItems(ACTION_KINDS)
        kind_box.setCurrentText(action_kind(action) if action is not None else "passthrough")
        detail_edit = QComboBox()
        detail_edit.setEditable(True)
        detail_edit.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        row = QHBoxLayout()
        row.addWidget(kind_box)
        row.addWidget(detail_edit)
        root = QWidget()
        root.setLayout(row)
        button_row = ButtonRow(
            root=root, control_id=control, kind_box=kind_box, detail_edit=detail_edit
        )
        kind_box.currentTextChanged.connect(partial(self._kind_changed, button_row))
        detail_edit.currentTextChanged.connect(self._detail_changed)
        self._sync_detail_options(button_row, action)
        return button_row

    def _selected_plate(self) -> int:
        value = self.plate_box.currentData()
        return int(value) if isinstance(value, int) else self._loaded_plate

    def _plate_changed(self) -> None:
        document = self.model.configuration_document
        if document is None:
            return
        try:
            configuration = parse_toml(document)
        except ConfigValidationError:
            return
        self._load(configuration, plate_layout=self._selected_plate())

    def _kind_changed(self, row: ButtonRow, text: str) -> None:
        self._sync_detail_options(row)
        self._update_dirty()

    def _detail_changed(self, _text: str) -> None:
        self._update_dirty()

    def _sync_detail_options(self, row: ButtonRow, action: Action | None = None) -> None:
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

    def _current_actions(self) -> dict[str, tuple[str, str]]:
        return {row.control_id: (row.selected_kind(), row.selected_detail()) for row in self.rows}

    def _is_dirty(self) -> bool:
        if self._selected_plate() != self._loaded_plate:
            return True
        for control, (kind, detail) in self._current_actions().items():
            loaded = self._loaded_actions[control]
            loaded_kind = action_kind(loaded) if loaded is not None else "passthrough"
            if kind != loaded_kind:
                return True
            if loaded is not None and detail != format_action_detail(loaded):
                return True
        return False

    def _update_dirty(self) -> None:
        dirty = self._is_dirty()
        self.apply_button.setEnabled(dirty)
        if self.model.apply_status is None:
            self.status_label.setText("unsaved changes" if dirty else "")

    def _apply(self) -> None:
        document = self.model.configuration_document
        if document is None:
            self.model.set_apply_status("service unreachable")
            return
        try:
            replacements: dict[LogicalControlId, Action | None] = {}
            for control, (kind, detail) in self._current_actions().items():
                replacements[cast(LogicalControlId, control)] = (
                    None if kind == "passthrough" else parse_action(kind, detail)
                )
            profile_id = parse_toml(document).active_profile
            updated = set_bindings(document, profile_id, replacements)
            if self._selected_plate() != self._loaded_plate:
                updated = set_plate_layout(updated, profile_id, self._selected_plate())
        except ConfigValidationError as exc:
            self.model.set_apply_status(f"rejected: {exc.message}")
            return
        self.model.set_apply_status("applying…")
        self._run(lambda: self._apply_document(updated))

    async def _apply_document(self, document: str) -> None:
        outcome = await self.presenter.apply_configuration(document)
        self.model.set_apply_status(_OUTCOME_TEXT[outcome])
        if outcome is ApplyOutcome.STALE:
            await self.presenter.refresh()
