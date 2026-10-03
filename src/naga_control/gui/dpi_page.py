"""Compact DPI stage editor, also used as a managed Settings section."""

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from naga_control.config import parse_toml
from naga_control.domain.profiles import Profile
from naga_control.gui.editors import set_dpi_stages
from naga_control.gui.models import ServiceModel
from naga_control.gui.presenter import GuiPresenter
from naga_control.gui.settings_page import ProfileSettingsPage
from naga_control.gui.worker import Runner

MIN_DPI = 100
MAX_DPI = 50000
MAX_STAGES = 5


@dataclass
class StageRow:
    root: QWidget
    x_spin: QSpinBox
    y_spin: QSpinBox


class DpiPage(ProfileSettingsPage):
    """Keep saved values separate from stage additions, removals, and edits."""

    def __init__(
        self, presenter: GuiPresenter, model: ServiceModel, run: Runner, *, managed: bool = False
    ) -> None:
        super().__init__(presenter, model, run, managed=managed)
        self.rows: list[StageRow] = []
        self._loaded_stages: list[tuple[int, int]] = []
        self._loaded_active = 1
        self.stage_area = QVBoxLayout()
        self.stage_area.setSpacing(2)
        self.active_box = QComboBox()
        self.active_box.setMaximumWidth(110)
        self.active_box.currentIndexChanged.connect(self._update_dirty)
        self.add_button = QPushButton("Add stage")
        self.add_button.setMaximumWidth(110)
        self.form.addRow("Active stage", self.active_box)
        self.form.addRow(self.stage_area)
        self.form.addRow(self.add_button)
        self.add_button.clicked.connect(self.add_stage)
        self._on_model_changed()

    def _load(self, profile: Profile) -> None:
        self._loaded_stages = [(stage.x, stage.y) for stage in profile.dpi.stages]
        self._loaded_active = profile.dpi.active_stage
        self._rebuild(self._loaded_stages, self._loaded_active)

    def _rebuild(self, stages: list[tuple[int, int]], active_stage: int) -> None:
        while self.stage_area.count():
            item = self.stage_area.takeAt(0)
            assert item is not None
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self.rows = []
        for index, (x, y) in enumerate(stages):
            self.rows.append(self._build_row(index, x, y))
        self.active_box.blockSignals(True)
        self.active_box.clear()
        self.active_box.addItems([str(i + 1) for i in range(len(self.rows))])
        self.active_box.setCurrentIndex(min(active_stage, len(self.rows)) - 1)
        self.active_box.blockSignals(False)
        self.add_button.setEnabled(len(self.rows) < MAX_STAGES)
        self._update_dirty()

    def _build_row(self, index: int, x: int, y: int) -> StageRow:
        x_spin = _dpi_spin(x)
        y_spin = _dpi_spin(y)
        remove = QPushButton("Remove")
        remove.setEnabled(index > 0)
        row = QHBoxLayout()
        row.setContentsMargins(0, 2, 0, 2)
        label = QLabel(f"Stage {index + 1}")
        label.setFixedWidth(55)
        row.addWidget(label)
        row.addWidget(QLabel("X"))
        row.addWidget(x_spin)
        row.addWidget(QLabel("Y"))
        row.addWidget(y_spin)
        row.addWidget(remove)
        row.addStretch()
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
        stages = self._current_stages()
        last = stages[-1] if stages else (1600, 1600)
        self._rebuild([*stages, last], self._current_active())

    def remove_stage(self, index: int) -> None:
        stages = self._current_stages()
        if not 0 <= index < len(stages) or len(stages) <= 1:
            return
        active = self._current_active()
        stages.pop(index)
        self._rebuild(stages, active - 1 if index + 1 < active else active)

    def _current_stages(self) -> list[tuple[int, int]]:
        return [(row.x_spin.value(), row.y_spin.value()) for row in self.rows]

    def _current_active(self) -> int:
        return self.active_box.currentIndex() + 1

    def _is_dirty(self) -> bool:
        return bool(self.rows) and (
            self._current_stages() != self._loaded_stages
            or self._current_active() != self._loaded_active
        )

    def _update_dirty(self) -> None:
        self._set_dirty(self._is_dirty())

    def _build_document(self, document: str) -> str:
        return set_dpi_stages(
            document,
            self.profile_id or parse_toml(document).active_profile,
            self._current_stages(),
            self._current_active(),
        )


def _dpi_spin(value: int) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(MIN_DPI, MAX_DPI)
    spin.setSingleStep(50)
    spin.setMaximumWidth(110)
    spin.setValue(value)
    return spin
