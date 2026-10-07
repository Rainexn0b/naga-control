"""Buttons page: edit control bindings of the active profile and apply them."""

from typing import cast

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from naga_control.config import parse_toml
from naga_control.domain.actions import Action
from naga_control.domain.errors import ConfigValidationError
from naga_control.domain.profiles import Configuration, LogicalControlId
from naga_control.gui.actions_view import (
    action_for_control,
    action_kind,
    format_action_detail,
    parse_action,
)
from naga_control.gui.buttons_rows import ButtonRow, build_button_row, sync_detail_options
from naga_control.gui.editors import set_bindings
from naga_control.gui.mapping_map import MappingMapView
from naga_control.gui.mapping_zones import MappingZone, all_zones
from naga_control.gui.models import ServiceModel
from naga_control.gui.presenter import ApplyOutcome, GuiPresenter
from naga_control.gui.worker import Runner

_OUTCOME_TEXT = {
    ApplyOutcome.APPLIED: "applied",
    ApplyOutcome.STALE: "changed on the service; reloaded, apply again",
    ApplyOutcome.INVALID: "rejected: invalid values",
    ApplyOutcome.UNREACHABLE: "service unreachable",
}


def _zone_order(zone: MappingZone) -> tuple[int, int]:
    plate_rank = {None: 0, 12: 1, 6: 2, 2: 3}[zone.plate]
    if zone.plate in (12, 6) and zone.control_id is not None:
        return plate_rank, int(zone.control_id.rpartition("_")[2])
    return plate_rank, zone.number


class ButtonsPage(QWidget):
    """Binding editor for the active profile with revision-checked apply."""

    model_changed = Signal()
    apply_finished = Signal()

    def __init__(self, presenter: GuiPresenter, model: ServiceModel, run: Runner) -> None:
        super().__init__()
        self.presenter = presenter
        self.model = model
        self._run = run
        self.rows: list[ButtonRow] = []
        self._loaded_actions: dict[str, Action | None] = {}
        self._loaded_document: str | None = None
        self.profile_id = ""
        self._pending_document: str | None = None
        self._dirty = False
        self._loading = False
        self.apply_finished.connect(self._finish_apply, Qt.ConnectionType.QueuedConnection)

        self.model.add_listener(self.model_changed.emit)
        self.model_changed.connect(self._on_model_changed, Qt.ConnectionType.QueuedConnection)

        self.profile_label = QLabel("unknown profile")
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.apply_button = QPushButton("Apply")
        self.apply_button.setEnabled(False)

        self.rows_area = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_area)
        self.rows_layout.setSpacing(2)
        self.rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.rows_scroll = QScrollArea()
        self.rows_scroll.setWidget(self.rows_area)
        self.rows_scroll.setWidgetResizable(True)

        self.mapping_map = MappingMapView()
        self.mapping_map.zone_selected.connect(self.select_control)
        map_hint = QLabel("Click a highlighted zone to jump to its binding")
        map_hint.setWordWrap(True)
        map_column = QVBoxLayout()
        map_column.setContentsMargins(0, 0, 0, 0)
        map_column.addWidget(self.mapping_map)
        map_column.addWidget(map_hint)
        map_panel = QWidget()
        map_panel.setLayout(map_column)

        actions = QHBoxLayout()
        actions.addWidget(self.apply_button)
        column = QVBoxLayout()
        column.addWidget(self.rows_scroll)
        column.addLayout(actions)
        column.addWidget(self.status_label)
        rows_panel = QWidget()
        rows_panel.setLayout(column)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(map_panel)
        self.splitter.addWidget(rows_panel)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([720, 480])
        outer = QVBoxLayout()
        outer.addWidget(self.splitter)
        self.setLayout(outer)

        self.apply_button.clicked.connect(self._apply)
        self.discard_button = QPushButton("Discard changes")
        self.discard_button.clicked.connect(self.discard_changes)
        actions.insertWidget(0, self.discard_button)
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
        if self.has_unsaved_changes() and self.profile_id != configuration.active_profile:
            self.status_label.setText(
                f"Unsaved bindings for {self.profile_id}. {self.model.apply_status or ''}"
            )
        if document != self._loaded_document:
            self._loaded_document = document
            if self.has_unsaved_changes() and document != self._pending_document:
                try:
                    updated = set_bindings(document, self.profile_id, self._replacements())
                    matches = (
                        self.profile_id == configuration.active_profile
                        and parse_toml(updated).profile(self.profile_id).bindings
                        == configuration.profile(self.profile_id).bindings
                    )
                except (ConfigValidationError, KeyError):
                    matches = False
                if not matches:
                    self.status_label.setText(f"Unsaved bindings retained for {self.profile_id}")
                    return
            self._pending_document = None
            self._load(configuration)

    def _load(self, configuration: Configuration) -> None:
        self._loading = True
        profile = configuration.profile(configuration.active_profile)
        self.profile_id = configuration.active_profile
        self._loaded_actions = {}
        # Remove entire rows, including labels, before rebuilding on a new revision.
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            assert item is not None
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self.rows = []
        self._highlighted_row: ButtonRow | None = None
        headings = QWidget()
        header = QHBoxLayout(headings)
        header.setContentsMargins(4, 2, 4, 2)
        for text, width in (("No.", 32), ("Button", 100), ("Action", 0), ("Binding", 0)):
            label = QLabel(f"<b>{text}</b>")
            if width:
                label.setFixedWidth(width)
            header.addWidget(label, 0 if width else 1)
        self.rows_layout.addWidget(headings)
        for zone in sorted(all_zones(), key=_zone_order):
            control = zone.control_id
            if control is None:
                root = QWidget()
                layout = QHBoxLayout(root)
                layout.setContentsMargins(4, 2, 4, 2)
                number = QLabel(str(zone.number))
                number.setFixedWidth(32)
                label = QLabel(zone.label if zone.number != 5 else "Wheel")
                label.setFixedWidth(100)
                layout.addWidget(number)
                layout.addWidget(label)
                layout.addWidget(QLabel("Passthrough (not remappable)"), 1)
                self.rows_layout.addWidget(root)
                continue
            action = action_for_control(profile.bindings, control)
            self._loaded_actions[control] = action
            row = build_button_row(
                control,
                action,
                zone.number,
                zone.label,
                on_kind_changed=self._kind_changed,
                on_detail_changed=self._detail_changed,
                on_recorded=self._recorded,
            )
            self.rows.append(row)
            self.rows_layout.addWidget(row.root)
        self.mapping_map.set_actions(self._loaded_actions)
        self.mapping_map.set_selected(None)
        self._update_dirty()
        self._loading = False

    def select_control(self, control_id: str) -> None:
        """Focus the binding row for a control picked on the mapping image."""
        row = next((row for row in self.rows if row.control_id == control_id), None)
        if row is None:
            return
        if self._highlighted_row is not None and self._highlighted_row is not row:
            self._highlighted_row.root.setStyleSheet("")
        self._highlighted_row = row
        row.root.setStyleSheet("background-color: rgba(68, 255, 136, 40);")
        self.mapping_map.set_selected(control_id)
        self.rows_scroll.ensureWidgetVisible(row.root)
        row.kind_box.setFocus()

    def _recorded(self, row: ButtonRow, kind: str, detail: str) -> None:
        row.kind_box.setCurrentText(kind)
        row.detail_edit.setCurrentText(detail)

    def _kind_changed(self, row: ButtonRow, text: str) -> None:
        row.record_button.cancel()
        sync_detail_options(row)
        self._update_dirty()

    def _detail_changed(self, _text: str) -> None:
        self._update_dirty()

    def _current_actions(self) -> dict[str, tuple[str, str]]:
        return {row.control_id: (row.selected_kind(), row.selected_detail()) for row in self.rows}

    def _is_dirty(self) -> bool:
        for control, (kind, detail) in self._current_actions().items():
            loaded = self._loaded_actions[control]
            loaded_kind = action_kind(loaded) if loaded is not None else "passthrough"
            if kind != loaded_kind:
                return True
            if loaded is not None and detail != format_action_detail(loaded):
                return True
        return False

    def _update_dirty(self) -> None:
        was_dirty = self._dirty
        dirty = self._is_dirty()
        self._dirty = dirty
        self.apply_button.setEnabled(dirty)
        self.discard_button.setEnabled(dirty)
        if dirty or self.model.apply_status is None:
            self.status_label.setText("unsaved changes" if dirty else "")
        if was_dirty and not dirty and not self._loading:
            self._loaded_document = None
            self._on_model_changed()

    def has_unsaved_changes(self) -> bool:
        return self._is_dirty()

    def discard_changes(self) -> None:
        self._loaded_actions = {}
        self.rows = []
        self._loaded_document = None
        self._on_model_changed()

    def _replacements(self) -> dict[LogicalControlId, Action | None]:
        replacements: dict[LogicalControlId, Action | None] = {}
        for control, (kind, detail) in self._current_actions().items():
            loaded = self._loaded_actions[control]
            loaded_kind = action_kind(loaded) if loaded is not None else "passthrough"
            if kind == loaded_kind and (loaded is None or detail == format_action_detail(loaded)):
                continue
            replacements[cast(LogicalControlId, control)] = (
                None if kind == "passthrough" else parse_action(kind, detail)
            )
        return replacements

    def _apply(self) -> None:
        document = self.model.configuration_document
        if document is None:
            self.model.set_apply_status("service unreachable")
            return
        try:
            updated = set_bindings(document, self.profile_id, self._replacements())
        except (ConfigValidationError, KeyError) as exc:
            self.model.set_apply_status(f"rejected: {exc}")
            return
        self._pending_document = updated
        self.setEnabled(False)
        self.model.set_apply_status("applying…")
        self._run(lambda: self._apply_document(updated))

    async def _apply_document(self, document: str) -> None:
        outcome = await self.presenter.apply_configuration(document)
        self.model.set_apply_status(_OUTCOME_TEXT[outcome])
        if outcome is not ApplyOutcome.APPLIED:
            self._pending_document = None
        self.apply_finished.emit()
        if outcome is ApplyOutcome.STALE:
            await self.presenter.refresh()

    def _finish_apply(self) -> None:
        self.setEnabled(True)
