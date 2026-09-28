"""Profiles page: list, duplicate, rename, and remove configuration profiles."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
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
from naga_control.gui.editors import duplicate_profile, remove_profile, rename_profile
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
    """Immediate profile actions; every change goes through the apply flow."""

    model_changed = Signal()

    def __init__(self, presenter: GuiPresenter, model: ServiceModel, run: Runner) -> None:
        super().__init__()
        self.presenter = presenter
        self.model = model
        self._run = run
        self._loaded_document: str | None = None
        self._updating_list = False

        self.model.add_listener(self.model_changed.emit)
        self.model_changed.connect(self._on_model_changed, Qt.ConnectionType.QueuedConnection)

        self.list_widget = QListWidget()
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.new_button = QPushButton("New from selected…")
        self.rename_button = QPushButton("Rename…")
        self.delete_button = QPushButton("Delete")

        buttons = QHBoxLayout()
        buttons.addWidget(self.new_button)
        buttons.addWidget(self.rename_button)
        buttons.addWidget(self.delete_button)
        column = QVBoxLayout()
        column.addWidget(self.list_widget)
        column.addLayout(buttons)
        column.addWidget(self.status_label)
        self.setLayout(column)

        self.new_button.clicked.connect(self._new_from_selected)
        self.rename_button.clicked.connect(self._rename_selected)
        self.delete_button.clicked.connect(self._delete_selected)
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
        if document != self._loaded_document:
            self._loaded_document = document
            self._reload_list(configuration)

    def _reload_list(self, configuration: Configuration) -> None:
        selected = self.list_widget.currentItem().text() if self.list_widget.currentItem() else ""
        self._updating_list = True
        try:
            self.list_widget.clear()
            for identifier, profile in configuration.profiles:
                label = f"{profile.display_name} ({identifier})"
                if identifier == configuration.active_profile:
                    label = f"▸ {label}"
                self.list_widget.addItem(label)
            if selected:
                for index in range(self.list_widget.count()):
                    if self.list_widget.item(index).text().endswith(f"({self._id_of(selected)})"):
                        self.list_widget.setCurrentRow(index)
                        break
        finally:
            self._updating_list = False
        self.delete_button.setEnabled(self.list_widget.count() > 1)

    def _id_of(self, list_label: str) -> str:
        return list_label.rstrip(")").rpartition("(")[2]

    def _selected_id(self) -> str | None:
        item = self.list_widget.currentItem()
        return self._id_of(item.text()) if item else None

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
        try:
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
