"""Shared behavior for pages that edit settings of the active profile."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from naga_control.config import parse_toml
from naga_control.domain.errors import ConfigValidationError
from naga_control.domain.profiles import Profile
from naga_control.gui.models import ServiceModel
from naga_control.gui.presenter import ApplyOutcome, GuiPresenter
from naga_control.gui.worker import Runner

OUTCOME_TEXT = {
    ApplyOutcome.APPLIED: "applied",
    ApplyOutcome.STALE: "changed on the service; reloaded, apply again",
    ApplyOutcome.INVALID: "rejected: invalid values",
    ApplyOutcome.UNREACHABLE: "service unreachable",
}


class ProfileSettingsPage(QWidget):
    """Common reload, dirty, and apply flow; subclasses fill the form."""

    model_changed = Signal()
    dirty_changed = Signal()
    apply_finished = Signal()

    def __init__(
        self, presenter: GuiPresenter, model: ServiceModel, run: Runner, *, managed: bool = False
    ) -> None:
        super().__init__()
        self.presenter = presenter
        self.model = model
        self._run = run
        self._loaded_document: str | None = None
        self._dirty = False
        self._loading_profile = False
        self.profile_id = ""
        self._managed = managed
        self._pending_document: str | None = None
        self.apply_finished.connect(self._finish_apply, Qt.ConnectionType.QueuedConnection)

        if not managed:
            self.model.add_listener(self.model_changed.emit)
            self.model_changed.connect(self._on_model_changed, Qt.ConnectionType.QueuedConnection)

        self.profile_label = QLabel("unknown profile")
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.apply_button = QPushButton("Apply")
        self.apply_button.setEnabled(False)
        self.discard_button = QPushButton("Discard changes")
        self.discard_button.setEnabled(False)

        self.form = QFormLayout()
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.header_widget = QWidget()
        header = QFormLayout(self.header_widget)
        header.addRow("Profile", self.profile_label)
        self.footer_widget = QWidget()
        footer = QVBoxLayout(self.footer_widget)
        footer.setContentsMargins(0, 0, 0, 0)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(self.discard_button)
        actions.addWidget(self.apply_button)
        footer.addLayout(actions)
        footer.addWidget(self.status_label)
        column = QVBoxLayout()
        column.setAlignment(Qt.AlignmentFlag.AlignTop)
        if not managed:
            column.addWidget(self.header_widget)
        column.addLayout(self.form)
        if not managed:
            column.addWidget(self.footer_widget)
        else:
            self.header_widget.hide()
            self.footer_widget.hide()
        self.setLayout(column)

        self.apply_button.clicked.connect(self._apply)
        self.discard_button.clicked.connect(self.discard_changes)

    def _on_model_changed(self) -> None:
        if self._managed:
            return
        self.status_label.setText(self.model.apply_status or "")
        document = self.model.configuration_document
        if document is None:
            return
        try:
            configuration = parse_toml(document)
        except ConfigValidationError:
            self.status_label.setText("service configuration is unreadable")
            return
        if self.has_unsaved_changes() and self.profile_id != configuration.active_profile:
            self.status_label.setText(
                f"Unsaved changes for {self.profile_id}. {self.model.apply_status or ''}"
            )
        if document != self._loaded_document:
            self._loaded_document = document
            if self.has_unsaved_changes() and document != self._pending_document:
                try:
                    replacement = parse_toml(self._build_document(document))
                    matches = (
                        self.profile_id == configuration.active_profile
                        and replacement.profile(self.profile_id)
                        == configuration.profile(self.profile_id)
                    )
                except (ConfigValidationError, KeyError):
                    matches = False
                if not matches:
                    self.status_label.setText(f"Unsaved changes retained for {self.profile_id}")
                    return
            self._pending_document = None
            self.load_profile(
                configuration.active_profile, configuration.profile(configuration.active_profile)
            )

    def _set_dirty(self, dirty: bool) -> None:
        was_dirty = self._dirty
        self._dirty = dirty
        self.apply_button.setEnabled(dirty)
        self.discard_button.setEnabled(dirty)
        if dirty or self.model.apply_status is None:
            self.status_label.setText("unsaved changes" if dirty else "")
        if was_dirty and not dirty and not self._loading_profile and not self._managed:
            self._loaded_document = None
            self._on_model_changed()
        self.dirty_changed.emit()

    def has_unsaved_changes(self) -> bool:
        return self._dirty

    def load_profile(self, profile_id: str, profile: Profile) -> None:
        self._loading_profile = True
        try:
            self.profile_id = profile_id
            self.profile_label.setText(profile_id)
            self._load(profile)
            self._set_dirty(False)
        finally:
            self._loading_profile = False

    def build_document(self, document: str) -> str:
        return self._build_document(document)

    def discard_changes(self) -> None:
        self._dirty = False
        self._loaded_document = None
        self._on_model_changed()

    def _apply(self) -> None:
        document = self.model.configuration_document
        if document is None:
            self.model.set_apply_status("service unreachable")
            return
        try:
            updated = self._build_document(document)
        except (ConfigValidationError, KeyError) as exc:
            self.model.set_apply_status(f"rejected: {exc}")
            return
        self._pending_document = updated
        self.setEnabled(False)
        self.model.set_apply_status("applying…")
        self._run(lambda: self._apply_document(updated))

    async def _apply_document(self, document: str) -> None:
        outcome = await self.presenter.apply_configuration(document)
        self.model.set_apply_status(OUTCOME_TEXT[outcome])
        if outcome is not ApplyOutcome.APPLIED:
            self._pending_document = None
        self.apply_finished.emit()
        if outcome is ApplyOutcome.STALE:
            await self.presenter.refresh()

    def _finish_apply(self) -> None:
        self.setEnabled(True)

    def _load(self, profile: Profile) -> None:
        raise NotImplementedError

    def _build_document(self, document: str) -> str:
        raise NotImplementedError
