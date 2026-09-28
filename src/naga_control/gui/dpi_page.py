"""DPI page: edit the active profile's stages and apply them atomically."""

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from naga_control.config import parse_toml
from naga_control.domain.errors import ConfigValidationError
from naga_control.domain.profiles import Configuration
from naga_control.gui.editors import set_dpi_stages
from naga_control.gui.models import ServiceModel
from naga_control.gui.presenter import ApplyOutcome, GuiPresenter
from naga_control.gui.worker import Runner

MIN_DPI = 100
MAX_DPI = 50000
MAX_STAGES = 5

_OUTCOME_TEXT = {
    ApplyOutcome.APPLIED: "applied",
    ApplyOutcome.STALE: "changed on the service; reloaded, apply again",
    ApplyOutcome.INVALID: "rejected: invalid values",
    ApplyOutcome.UNREACHABLE: "service unreachable",
}


@dataclass
class StageRow:
    root: QWidget
    x_spin: QSpinBox
    y_spin: QSpinBox


class DpiPage(QWidget):
    """Stage editor for the active profile with revision-checked apply."""

    model_changed = Signal()

    def __init__(self, presenter: GuiPresenter, model: ServiceModel, run: Runner) -> None:
        super().__init__()
        self.presenter = presenter
        self.model = model
        self._run = run
        self.rows: list[StageRow] = []
        self._loaded_stages: list[tuple[int, int]] = []
        self._loaded_active = 1
        self._loaded_document: str | None = None

        self.model.add_listener(self.model_changed.emit)
        self.model_changed.connect(self._on_model_changed, Qt.ConnectionType.QueuedConnection)

        self.profile_label = QLabel("unknown profile")
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.stage_area = QVBoxLayout()
        self.active_box = QComboBox()
        self.add_button = QPushButton("Add stage")
        self.apply_button = QPushButton("Apply")
        self.apply_button.setEnabled(False)

        form = QFormLayout()
        form.addRow("Profile", self.profile_label)
        form.addRow("Active stage", self.active_box)
        buttons = QHBoxLayout()
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.apply_button)
        column = QVBoxLayout()
        column.addLayout(form)
        column.addLayout(self.stage_area)
        column.addLayout(buttons)
        column.addWidget(self.status_label)
        self.setLayout(column)

        self.add_button.clicked.connect(self.add_stage)
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

    def _load(self, configuration: Configuration) -> None:
        profile = configuration.profile(configuration.active_profile)
        self._loaded_stages = [(stage.x, stage.y) for stage in profile.dpi.stages]
        self._loaded_active = profile.dpi.active_stage
        self._rebuild()

    def _rebuild(self) -> None:
        for row in self.rows:
            row.root.deleteLater()
        self.rows = []
        for index, (x, y) in enumerate(self._loaded_stages):
            self.rows.append(self._build_row(index, x, y))
        self.active_box.blockSignals(True)
        try:
            self.active_box.clear()
            self.active_box.addItems([str(i + 1) for i in range(len(self.rows))])
            self.active_box.setCurrentIndex(min(self._loaded_active, len(self.rows)) - 1)
        finally:
            self.active_box.blockSignals(False)
        self.add_button.setEnabled(len(self.rows) < MAX_STAGES)
        self._update_dirty()

    def _build_row(self, index: int, x: int, y: int) -> StageRow:
        x_spin = _dpi_spin(x)
        y_spin = _dpi_spin(y)
        remove = QPushButton("Remove")
        remove.setEnabled(index > 0)
        row = QHBoxLayout()
        row.addWidget(QLabel(f"Stage {index + 1}"))
        row.addWidget(QLabel("X"))
        row.addWidget(x_spin)
        row.addWidget(QLabel("Y"))
        row.addWidget(y_spin)
        row.addWidget(remove)
        root = QWidget()
        root.setLayout(row)
        self.stage_area.addWidget(root)
        stage_row = StageRow(root=root, x_spin=x_spin, y_spin=y_spin)
        remove.clicked.connect(lambda: self.remove_stage(self.rows.index(stage_row)))
        x_spin.valueChanged.connect(self._update_dirty)
        y_spin.valueChanged.connect(self._update_dirty)
        return stage_row

    def add_stage(self) -> None:
        if len(self.rows) >= MAX_STAGES:
            return
        last = (
            (self.rows[-1].x_spin.value(), self.rows[-1].y_spin.value())
            if self.rows
            else (1600, 1600)
        )
        self._loaded_stages = [*self._current_stages(), last]
        self._rebuild()

    def remove_stage(self, index: int) -> None:
        stages = self._current_stages()
        if not 0 <= index < len(stages) or len(stages) <= 1:
            return
        stages.pop(index)
        self._loaded_stages = stages
        self._rebuild()

    def _current_stages(self) -> list[tuple[int, int]]:
        return [(row.x_spin.value(), row.y_spin.value()) for row in self.rows]

    def _current_active(self) -> int:
        return self.active_box.currentIndex() + 1

    def _is_dirty(self) -> bool:
        return bool(self.rows) and (
            self._current_stages() != self._loaded_stages
            or self._current_active() != min(self._loaded_active, len(self.rows))
        )

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
            updated = set_dpi_stages(
                document,
                parse_toml(document).active_profile,
                self._current_stages(),
                self._current_active(),
            )
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


def _dpi_spin(value: int) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(MIN_DPI, MAX_DPI)
    spin.setSingleStep(50)
    spin.setValue(value)
    return spin
