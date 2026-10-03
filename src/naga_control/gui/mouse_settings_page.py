"""One atomic editor for sensitivity, scrolling, and lighting settings."""

from dataclasses import replace
from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QGroupBox, QVBoxLayout, QWidget

from naga_control.config import dump_toml, parse_toml
from naga_control.domain.profiles import Profile
from naga_control.gui.dpi_page import DpiPage
from naga_control.gui.editors import edit_profile
from naga_control.gui.lighting_page import LightingPage
from naga_control.gui.models import ServiceModel
from naga_control.gui.presenter import GuiPresenter
from naga_control.gui.scroll_page import ScrollPage
from naga_control.gui.settings_page import ProfileSettingsPage
from naga_control.gui.two_columns import TwoColumns
from naga_control.gui.worker import Runner


class MouseSettingsPage(ProfileSettingsPage):
    """Own a shared draft and one revision-checked Apply for all three sections."""

    def __init__(self, presenter: GuiPresenter, model: ServiceModel, run: Runner) -> None:
        super().__init__(presenter, model, run)
        self._loading = False
        self._loaded_poll_rate = 1000
        self.dpi = DpiPage(presenter, model, run, managed=True)
        self.scroll_section = ScrollPage(presenter, model, run, managed=True)
        self.lighting = LightingPage(presenter, model, run, managed=True)
        self.poll_rate_box = QComboBox()
        for rate in (125, 500, 1000):
            self.poll_rate_box.addItem(f"{rate} Hz", rate)
        self.poll_rate_box.setMaximumWidth(180)
        self.dpi.form.addRow("Polling rate", self.poll_rate_box)

        sensitivity = QGroupBox("Sensitivity")
        QVBoxLayout(sensitivity).addWidget(self.dpi)
        scrolling = QGroupBox("Scroll")
        QVBoxLayout(scrolling).addWidget(self.scroll_section)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(sensitivity)
        left_layout.addWidget(scrolling)
        left_layout.addStretch()
        lighting = QGroupBox("Lighting")
        QVBoxLayout(lighting).addWidget(self.lighting)
        self.columns = TwoColumns(left, lighting)
        column = cast(QVBoxLayout, self.layout())
        column.removeItem(self.form)
        column.insertWidget(1, self.columns, 1)
        column.setAlignment(Qt.AlignmentFlag(0))
        self.header_widget.hide()
        self.apply_button.setText("Apply Settings")
        for section in (self.dpi, self.scroll_section, self.lighting):
            section.dirty_changed.connect(self._check_dirty)
        self.poll_rate_box.currentIndexChanged.connect(self._check_dirty)
        self._on_model_changed()

    def _load(self, profile: Profile) -> None:
        self._loading = True
        try:
            for section in (self.dpi, self.scroll_section, self.lighting):
                section.load_profile(self.profile_id, profile)
            self._loaded_poll_rate = profile.poll_rate
            self.poll_rate_box.setCurrentIndex(self.poll_rate_box.findData(profile.poll_rate))
        finally:
            self._loading = False

    def _check_dirty(self) -> None:
        if not self._loading:
            self._set_dirty(
                any(
                    section.has_unsaved_changes()
                    for section in (self.dpi, self.scroll_section, self.lighting)
                )
                or self.poll_rate_box.currentData() != self._loaded_poll_rate
            )

    def _build_document(self, document: str) -> str:
        revision = parse_toml(document).revision
        updated = document
        for section in (self.dpi, self.scroll_section, self.lighting):
            if section.has_unsaved_changes():
                updated = section.build_document(updated)
        if self.poll_rate_box.currentData() != self._loaded_poll_rate:
            rate = cast(int, self.poll_rate_box.currentData())
            updated = edit_profile(
                updated, self.profile_id, lambda profile: replace(profile, poll_rate=rate)
            )
        # Section transforms compose locally; the service receives exactly one revision.
        return dump_toml(replace(parse_toml(updated), revision=revision + 1))
