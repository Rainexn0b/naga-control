"""Profiles page: manage profiles and their manually selected attached plate."""

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
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
from naga_control.gui.worker import Runner

OUTCOME_TEXT = {
    ApplyOutcome.APPLIED: "applied",
    ApplyOutcome.STALE: "changed on the service; reloaded, apply again",
    ApplyOutcome.INVALID: "rejected: invalid values",
    ApplyOutcome.UNREACHABLE: "service unreachable",
}


class ProfilesPage(QWidget):
    """Profile actions and explicit plate changes through the apply flow."""

    model_changed = Signal()

    def __init__(self, presenter: GuiPresenter, model: ServiceModel, run: Runner) -> None:
        super().__init__()
        self.presenter = presenter
        self.model = model
        self._run = run
        self._loaded_document: str | None = None
        self._configuration: Configuration | None = None
        self._updating_list = False
        self.confirm_profile_change: Callable[[], bool] = lambda: True

        self.model.add_listener(self.model_changed.emit)
        self.model_changed.connect(self._on_model_changed, Qt.ConnectionType.QueuedConnection)

        self.list_widget = QListWidget()
        self.list_widget.setMaximumHeight(220)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.new_button = QPushButton("New from selected…")
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

        plate_form = QFormLayout()
        plate_form.addRow("Attached plate", self.plate_box)
        plate_form.addRow(self.apply_plate_button)

        buttons = QHBoxLayout()
        buttons.addWidget(self.new_button)
        buttons.addWidget(self.rename_button)
        buttons.addWidget(self.delete_button)
        column = QVBoxLayout()
        column.setAlignment(Qt.AlignmentFlag.AlignTop)
        column.addWidget(self.list_widget)
        column.addLayout(buttons)
        column.addLayout(plate_form)
        column.addWidget(self.status_label)
        self.setLayout(column)

        self.new_button.clicked.connect(self._new_from_selected)
        self.rename_button.clicked.connect(self._rename_selected)
        self.delete_button.clicked.connect(self._delete_selected)
        self.list_widget.currentItemChanged.connect(self._load_selected_plate)
        self.plate_box.currentIndexChanged.connect(self._update_plate_enabled)
        self.apply_plate_button.clicked.connect(self._apply_plate)
        self._on_model_changed()

    def _on_model_changed(self) -> None:
        pending_layout = self.plate_box.currentData() if self.has_unsaved_changes() else None
        pending_id = self._selected_id()
        self.status_label.setText(self.model.apply_status or "")
        document = self.model.configuration_document
        if document is None:
            self._configuration = None
            self._load_selected_plate()
            return
        try:
            configuration = parse_toml(document)
        except ConfigValidationError:
            self._configuration = None
            self._load_selected_plate()
            self.status_label.setText("service configuration is unreadable")
            return
        reload = document != self._loaded_document or self._configuration is None
        self._configuration = configuration
        if reload:
            self._loaded_document = document
            self._reload_list(configuration)
            if pending_layout is not None and self._selected_id() == pending_id:
                self.plate_box.setCurrentIndex(self.plate_box.findData(pending_layout))
        self._update_plate_enabled()

    def _reload_list(self, configuration: Configuration) -> None:
        selected = self._selected_id() or configuration.active_profile
        if selected not in {identifier for identifier, _ in configuration.profiles}:
            selected = configuration.active_profile
        self._updating_list = True
        try:
            self.list_widget.clear()
            for identifier, profile in configuration.profiles:
                label = f"{profile.display_name} ({identifier})"
                if identifier == configuration.active_profile:
                    label = f"▸ {label}"
                self.list_widget.addItem(label)
            for index in range(self.list_widget.count()):
                if self.list_widget.item(index).text().endswith(f"({selected})"):
                    self.list_widget.setCurrentRow(index)
                    break
        finally:
            self._updating_list = False
        self._load_selected_plate()

    def _id_of(self, list_label: str) -> str:
        return list_label.rstrip(")").rpartition("(")[2]

    def _selected_id(self) -> str | None:
        item = self.list_widget.currentItem()
        return self._id_of(item.text()) if item else None

    def has_unsaved_changes(self) -> bool:
        selected = self._selected_id()
        if self._configuration is None or selected is None:
            return False
        try:
            return (
                self.plate_box.currentData() != self._configuration.profile(selected).plate_layout
            )
        except KeyError:
            return False

    def discard_changes(self) -> None:
        self._load_selected_plate()

    def _load_selected_plate(self) -> None:
        if self._updating_list:
            return
        selected = self._selected_id()
        index = -1
        if self._configuration is not None and selected is not None:
            try:
                layout = self._configuration.profile(selected).plate_layout
                index = self.plate_box.findData(layout)
            except KeyError:
                pass
        self.plate_box.setCurrentIndex(index)
        self._update_plate_enabled()

    def _update_plate_enabled(self) -> None:
        selected = self._selected_id()
        enabled = (
            self.model.connection.reachable
            and self._configuration is not None
            and selected in {identifier for identifier, _ in self._configuration.profiles}
        )
        self.new_button.setEnabled(enabled)
        self.rename_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled and self.list_widget.count() > 1)
        plate_enabled = enabled and self.plate_box.currentData() in (12, 6, 2)
        self.plate_box.setEnabled(plate_enabled)
        self.apply_plate_button.setEnabled(plate_enabled)

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

        ok = False
        answer, ok = QInputDialog.getText(self, title, label, text=default)
        return answer.strip() if ok and answer.strip() else None

    def _confirm(self, title: str, message: str) -> bool:
        result = QMessageBox.question(self, title, message)
        return result == QMessageBox.StandardButton.Yes
