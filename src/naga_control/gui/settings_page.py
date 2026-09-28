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

    def __init__(self, presenter: GuiPresenter, model: ServiceModel, run: Runner) -> None:
        super().__init__()
        self.presenter = presenter
        self.model = model
        self._run = run
        self._loaded_document: str | None = None
        self._dirty = False

        self.model.add_listener(self.model_changed.emit)
        self.model_changed.connect(self._on_model_changed, Qt.ConnectionType.QueuedConnection)

        self.profile_label = QLabel("unknown profile")
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.apply_button = QPushButton("Apply")
        self.apply_button.setEnabled(False)

        self.form = QFormLayout()
        header = QFormLayout()
        header.addRow("Profile", self.profile_label)
        actions = QHBoxLayout()
        actions.addWidget(self.apply_button)
        column = QVBoxLayout()
        column.addLayout(header)
        column.addLayout(self.form)
        column.addLayout(actions)
        column.addWidget(self.status_label)
        self.setLayout(column)

        self.apply_button.clicked.connect(self._apply)

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
            self._load(configuration.profile(configuration.active_profile))
            self._set_dirty(False)

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        self.apply_button.setEnabled(dirty)
        if self.model.apply_status is None:
            self.status_label.setText("unsaved changes" if dirty else "")

    def _apply(self) -> None:
        document = self.model.configuration_document
        if document is None:
            self.model.set_apply_status("service unreachable")
            return
        try:
            updated = self._build_document(document)
        except ConfigValidationError as exc:
            self.model.set_apply_status(f"rejected: {exc.message}")
            return
        self.model.set_apply_status("applying…")
        self._run(lambda: self._apply_document(updated))

    async def _apply_document(self, document: str) -> None:
        outcome = await self.presenter.apply_configuration(document)
        self.model.set_apply_status(OUTCOME_TEXT[outcome])
        if outcome is ApplyOutcome.STALE:
            await self.presenter.refresh()

    def _load(self, profile: Profile) -> None:
        raise NotImplementedError

    def _build_document(self, document: str) -> str:
        raise NotImplementedError
