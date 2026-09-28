"""Power page: idle timeout and low-battery threshold of the active profile."""

from PySide6.QtWidgets import QSpinBox

from naga_control.config import parse_toml
from naga_control.domain.profiles import Profile
from naga_control.gui.editors import set_power
from naga_control.gui.models import ServiceModel
from naga_control.gui.presenter import GuiPresenter
from naga_control.gui.settings_page import ProfileSettingsPage
from naga_control.gui.settings_view import power_values
from naga_control.gui.worker import Runner


class PowerPage(ProfileSettingsPage):
    """Two bounded numeric settings."""

    def __init__(self, presenter: GuiPresenter, model: ServiceModel, run: Runner) -> None:
        super().__init__(presenter, model, run)
        self.idle_spin = QSpinBox()
        self.idle_spin.setRange(60, 900)
        self.idle_spin.setSingleStep(30)
        self.idle_spin.setSuffix(" s")
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(0, 25)
        self.threshold_spin.setSuffix(" %")
        self.form.addRow("Sleep after idle", self.idle_spin)
        self.form.addRow("Low battery warning", self.threshold_spin)
        self._loaded: tuple[int, int] = (60, 0)

        self.idle_spin.valueChanged.connect(self._value_changed)
        self.threshold_spin.valueChanged.connect(self._value_changed)
        self._on_model_changed()

    def _value_changed(self, _value: int) -> None:
        self._set_dirty(self._current() != self._loaded)

    def _load(self, profile: Profile) -> None:
        idle, threshold = power_values(profile)
        self._loaded = (idle, threshold)
        self.idle_spin.setValue(idle)
        self.threshold_spin.setValue(threshold)

    def _current(self) -> tuple[int, int]:
        return (self.idle_spin.value(), self.threshold_spin.value())

    def _build_document(self, document: str) -> str:
        idle, threshold = self._current()
        return set_power(document, parse_toml(document).active_profile, idle, threshold)
