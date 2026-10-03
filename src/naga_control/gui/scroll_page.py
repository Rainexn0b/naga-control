"""Scroll page: mode, acceleration, and Smart Reel of the active profile."""

from PySide6.QtWidgets import QCheckBox, QComboBox

from naga_control.config import parse_toml
from naga_control.domain.profiles import Profile
from naga_control.gui.editors import set_scroll
from naga_control.gui.models import ServiceModel
from naga_control.gui.presenter import GuiPresenter
from naga_control.gui.settings_page import ProfileSettingsPage
from naga_control.gui.settings_view import SCROLL_MODES, scroll_values
from naga_control.gui.worker import Runner


class ScrollPage(ProfileSettingsPage):
    """Three controls for the scroll wheel behavior."""

    def __init__(
        self, presenter: GuiPresenter, model: ServiceModel, run: Runner, *, managed: bool = False
    ) -> None:
        super().__init__(presenter, model, run, managed=managed)
        self.mode_box = QComboBox()
        self.mode_box.addItems(SCROLL_MODES)
        self.mode_box.setMaximumWidth(240)
        self.acceleration_check = QCheckBox("Acceleration")
        self.smart_reel_check = QCheckBox("Smart Reel")
        self.form.addRow("Mode", self.mode_box)
        self.form.addRow("", self.acceleration_check)
        self.form.addRow("", self.smart_reel_check)
        self._loaded: tuple[str, bool, bool] = ("tactile", False, False)

        self.mode_box.currentTextChanged.connect(self._text_changed)
        self.acceleration_check.toggled.connect(self._flag_changed)
        self.smart_reel_check.toggled.connect(self._flag_changed)
        self._on_model_changed()

    def _text_changed(self, _text: str) -> None:
        self._check_dirty()

    def _flag_changed(self, _checked: bool) -> None:
        self._check_dirty()

    def _load(self, profile: Profile) -> None:
        mode, acceleration, smart_reel = scroll_values(profile)
        self._loaded = (mode, acceleration, smart_reel)
        self.mode_box.setCurrentText(mode)
        self.acceleration_check.setChecked(acceleration)
        self.smart_reel_check.setChecked(smart_reel)

    def _check_dirty(self) -> None:
        self._set_dirty(self._current() != self._loaded)

    def _current(self) -> tuple[str, bool, bool]:
        return (
            self.mode_box.currentText(),
            self.acceleration_check.isChecked(),
            self.smart_reel_check.isChecked(),
        )

    def _build_document(self, document: str) -> str:
        mode, acceleration, smart_reel = self._current()
        return set_scroll(
            document,
            self.profile_id or parse_toml(document).active_profile,
            mode,  # pyright: ignore[reportArgumentType]
            acceleration,
            smart_reel,
        )
