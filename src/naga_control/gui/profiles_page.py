"""Profiles page: unified dropdown for editing plus explicit activation."""

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from naga_control.config import parse_toml
from naga_control.domain.errors import ConfigValidationError
from naga_control.domain.profiles import Configuration
from naga_control.gui.editors import (
    duplicate_profile,
    remove_profile,
    rename_profile,
    set_plate_layout,
)
from naga_control.gui.models import ServiceModel
from naga_control.gui.presenter import ApplyOutcome, GuiPresenter
from naga_control.gui.profile_controls import activation_gate
from naga_control.gui.profile_mode_view import (
    PROFILE_MANAGEMENT_HELP,
    is_software_verified,
    software_profile_label,
)
from naga_control.gui.profile_plate_drafts import PlateDrafts
from naga_control.gui.worker import Runner

OUTCOME_TEXT = {
    ApplyOutcome.APPLIED: "applied",
    ApplyOutcome.STALE: "changed on the service; reloaded, apply again",
    ApplyOutcome.INVALID: "rejected: invalid values",
    ApplyOutcome.UNREACHABLE: "service unreachable",
}


class ProfilesPage(QWidget):
    """One dropdown manages selection; Activate switches via the shell guard."""

    model_changed = Signal()
    activate_requested = Signal(str)

    def __init__(self, presenter: GuiPresenter, model: ServiceModel, run: Runner) -> None:
        super().__init__()
        self.presenter = presenter
        self.model = model
        self._run = run
        self._loaded_document: str | None = None
        self._configuration: Configuration | None = None
        self._plate_drafts = PlateDrafts()
        self._updating = False
        self.confirm_profile_change: Callable[[], bool] = lambda: True

        self.model.add_listener(self.model_changed.emit)
        self.model_changed.connect(self._on_model_changed, Qt.ConnectionType.QueuedConnection)

        self.active_label = QLabel("Active: unknown")
        self.active_label.setWordWrap(True)
        self.profiles_box = QComboBox()
        self.profiles_box.setToolTip(PROFILE_MANAGEMENT_HELP)
        self.profiles_box.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.profiles_box.setMinimumContentsLength(12)
        self.activate_button = QPushButton("Activate")
        self.activate_button.setToolTip(
            "Switch to the selected profile. " + PROFILE_MANAGEMENT_HELP
        )
        self.help_label = QLabel("Choose a profile to edit; editors follow the active profile.")
        self.help_label.setWordWrap(True)
        self.draft_label = QLabel("")
        self.draft_label.setWordWrap(True)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.new_button = QPushButton("New…")
        self.rename_button = QPushButton("Rename…")
        self.delete_button = QPushButton("Delete")
        self.plate_box = QComboBox()
        for layout in (12, 6, 2):
            self.plate_box.addItem(f"{layout}-button", layout)
        self.plate_box.setToolTip(
            "Choose the attached plate manually for the selected profile; "
            "plates are not detected automatically. Click Apply plate to save."
        )
        self.apply_plate_button = QPushButton("Apply plate")

        selector_row = QHBoxLayout()
        selector_row.addWidget(self.profiles_box, 1)
        selector_row.addWidget(self.activate_button)
        plate_form = QFormLayout()
        plate_form.addRow("Attached plate", self.plate_box)
        plate_form.addRow(self.apply_plate_button)

        buttons = QHBoxLayout()
        buttons.addWidget(self.new_button)
        buttons.addWidget(self.rename_button)
        buttons.addWidget(self.delete_button)
        column = QVBoxLayout()
        column.setAlignment(Qt.AlignmentFlag.AlignTop)
        column.addWidget(self.active_label)
        column.addLayout(selector_row)
        column.addWidget(self.help_label)
        column.addLayout(buttons)
        column.addLayout(plate_form)
        column.addWidget(self.draft_label)
        column.addWidget(self.status_label)
        self.setLayout(column)

        self.profiles_box.currentIndexChanged.connect(self._selection_changed)
        self.plate_box.currentIndexChanged.connect(self._plate_changed)
        self.activate_button.clicked.connect(self._request_activate)
        self.new_button.clicked.connect(self._new_from_selected)
        self.rename_button.clicked.connect(self._rename_selected)
        self.delete_button.clicked.connect(self._delete_selected)
        self.apply_plate_button.clicked.connect(self._apply_plate)
        self._on_model_changed()

    def _selected_id(self) -> str | None:
        value = self.profiles_box.currentData()
        return value if isinstance(value, str) else None

    def _active_id(self) -> str | None:
        return self._configuration.active_profile if self._configuration is not None else None

    def _on_model_changed(self) -> None:
        self.status_label.setText(self.model.apply_status or "")
        document = self.model.configuration_document
        if document is None:
            self._configuration = None
            self._refresh_chrome()
            self._update_enabled()
            self._update_draft_label()
            return
        try:
            configuration = parse_toml(document)
        except ConfigValidationError:
            self._configuration = None
            self._refresh_chrome()
            self.status_label.setText("service configuration is unreadable")
            self._update_enabled()
            self._update_draft_label()
            return
        self._configuration = configuration
        self._plate_drafts.prune(configuration)
        if document != self._loaded_document:
            self._loaded_document = document
            self._rebuild_combo(configuration)
        else:
            self._refresh_chrome()
            self._load_selected_plate()
        self._update_enabled()
        self._update_draft_label()

    def _rebuild_combo(self, configuration: Configuration) -> None:
        previous = self._selected_id()
        identifiers = {identifier for identifier, _ in configuration.profiles}
        if previous not in identifiers:
            previous = configuration.active_profile
        self._updating = True
        try:
            self.profiles_box.blockSignals(True)
            self.profiles_box.clear()
            for identifier, profile in configuration.profiles:
                self.profiles_box.addItem(
                    software_profile_label(profile.display_name, identifier), identifier
                )
            self.profiles_box.setCurrentIndex(self.profiles_box.findData(previous))
        finally:
            self.profiles_box.blockSignals(False)
            self._updating = False
        self._refresh_chrome()
        self._load_selected_plate()
        self._update_enabled()
        self._update_draft_label()

    def _refresh_chrome(self) -> None:
        active = self._active_id()
        name: str | None = None
        if active is not None and self._configuration is not None:
            try:
                name = self._configuration.profile(active).display_name
            except KeyError:
                name = None
        if name is not None and active is not None:
            self.active_label.setText(f"Active: {software_profile_label(name, active)}")
        else:
            self.active_label.setText("Active: unknown")

    def _selection_changed(self, _index: int) -> None:
        if self._updating:
            return
        self._load_selected_plate()
        self._update_enabled()

    def _load_selected_plate(self) -> None:
        if self._updating:
            return
        selected = self._selected_id()
        layout = self._plate_drafts.get(selected)
        if layout is None and selected is not None and self._configuration is not None:
            try:
                layout = self._configuration.profile(selected).plate_layout
            except KeyError:
                layout = None
        self.plate_box.blockSignals(True)
        try:
            self.plate_box.setCurrentIndex(
                self.plate_box.findData(layout) if layout in (12, 6, 2) else -1
            )
        finally:
            self.plate_box.blockSignals(False)
        self._update_enabled()
        self._update_draft_label()

    def _plate_changed(self, _index: int) -> None:
        if self._updating:
            return
        selected = self._selected_id()
        if selected is None or self._configuration is None:
            return
        try:
            configured = self._configuration.profile(selected).plate_layout
        except KeyError:
            return
        self._plate_drafts.record(selected, configured, self.plate_box.currentData())
        self._update_draft_label()
        self._update_enabled()

    def _update_draft_label(self) -> None:
        pending = ", ".join(self._plate_drafts.pending_ids())
        self.draft_label.setText(f"Unsaved plate edits pending: {pending}" if pending else "")

    def _update_enabled(self) -> None:
        selected = self._selected_id()
        identifiers: set[str] = (
            {identifier for identifier, _ in self._configuration.profiles}
            if self._configuration is not None
            else set()
        )
        pending = self.model.apply_status == "applying…"
        editable = (
            self.model.connection.reachable
            and self._configuration is not None
            and selected in identifiers
            and not pending
        )
        self.profiles_box.setEnabled(
            self.model.connection.reachable and self._configuration is not None
        )
        self.new_button.setEnabled(bool(editable))
        self.rename_button.setEnabled(bool(editable))
        self.delete_button.setEnabled(bool(editable) and len(identifiers) > 1)
        plate_ok = bool(editable) and self.plate_box.currentData() in (12, 6, 2)
        self.plate_box.setEnabled(plate_ok)
        self.apply_plate_button.setEnabled(plate_ok)
        can_activate, tip = activation_gate(self.model, bool(editable), selected, self._active_id())
        self.activate_button.setEnabled(can_activate)
        self.activate_button.setToolTip(tip)

    def has_unsaved_changes(self) -> bool:
        return bool(self._plate_drafts)

    def discard_changes(self) -> None:
        self._plate_drafts.clear()
        self._load_selected_plate()

    def _request_activate(self) -> None:
        selected = self._selected_id()
        if selected is None or self._configuration is None:
            return
        if selected == self._configuration.active_profile:
            return
        if (
            not self.model.connection.reachable
            or not is_software_verified(self.model)
            or self.model.apply_status == "applying…"
        ):
            self._update_enabled()
            return
        self.activate_requested.emit(selected)

    def _apply_plate(self) -> None:
        selected = self._selected_id()
        if selected is None:
            return
        document = self._document_or_complain()
        if document is None or not self.model.connection.reachable:
            self.model.set_apply_status("service unreachable")
            return
        layout = self.plate_box.currentData()
        if type(layout) is not int or layout not in (12, 6, 2):
            self.model.set_apply_status("rejected: select an attached plate")
            return
        try:
            updated = set_plate_layout(document, selected, layout)
        except ConfigValidationError as exc:
            self.model.set_apply_status(f"rejected: {exc.message}")
            return
        except KeyError:
            self.model.set_apply_status("rejected: selected profile no longer exists")
            return
        self.apply_document(updated)

    def _new_from_selected(self) -> None:
        source = self._selected_id()
        if source is None:
            return
        answer = self._prompt("New profile", "Profile ID (lowercase slug):", f"{source}-copy")
        if answer is None:
            return
        document = self._document_or_complain()
        if document is None:
            return
        try:
            updated = duplicate_profile(document, source, answer, answer.replace("-", " ").title())
        except ConfigValidationError as exc:
            self.model.set_apply_status(f"rejected: {exc.message}")
            return
        self.apply_document(updated)

    def _rename_selected(self) -> None:
        profile_id = self._selected_id()
        if profile_id is None:
            return
        answer = self._prompt("Rename profile", "Display name:", profile_id)
        if answer is None:
            return
        self._submit_rename(profile_id, answer)

    def _delete_selected(self) -> None:
        profile_id = self._selected_id()
        if profile_id is None:
            return
        if not self._confirm("Delete profile", f"Delete {profile_id!r}?"):
            return
        self._submit_delete(profile_id)

    def _submit_rename(self, profile_id: str, display_name: str) -> None:
        document = self._document_or_complain()
        if document is None:
            return
        try:
            updated = rename_profile(document, profile_id, display_name)
        except ConfigValidationError as exc:
            self.model.set_apply_status(f"rejected: {exc.message}")
            return
        self.apply_document(updated)

    def _submit_delete(self, profile_id: str) -> None:
        document = self._document_or_complain()
        if document is None:
            return
        if not self.model.connection.reachable:
            self.model.set_apply_status("service unreachable")
            return
        try:
            configuration = parse_toml(document)
            if profile_id == configuration.active_profile and not self.confirm_profile_change():
                return
            updated = remove_profile(document, profile_id)
        except ConfigValidationError as exc:
            self.model.set_apply_status(f"rejected: {exc.message}")
            return
        self.apply_document(updated)

    def apply_document(self, updated: str) -> None:
        if self.model.apply_status == "applying…":
            return
        self.model.set_apply_status("applying…")
        self._run(lambda: self._send(updated))

    async def _send(self, updated: str) -> None:
        outcome = await self.presenter.apply_configuration(updated)
        self.model.set_apply_status(OUTCOME_TEXT[outcome])
        if outcome is ApplyOutcome.STALE:
            await self.presenter.refresh()

    def _document_or_complain(self) -> str | None:
        document = self.model.configuration_document
        if document is None:
            self.model.set_apply_status("service unreachable")
        return document

    def _prompt(self, title: str, label: str, default: str) -> str | None:
        from PySide6.QtWidgets import QInputDialog

        answer, ok = QInputDialog.getText(self, title, label, text=default)
        return answer.strip() if ok and answer.strip() else None

    def _confirm(self, title: str, message: str) -> bool:
        result = QMessageBox.question(self, title, message)
        return result == QMessageBox.StandardButton.Yes
