"""Lighting page: brightness and effects for the three lighting zones."""

from dataclasses import dataclass
from functools import partial

from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
)

from naga_control.config import parse_toml
from naga_control.domain.errors import ConfigValidationError
from naga_control.domain.profiles import LightingEffect, LightingSettings, LightingZone, Profile
from naga_control.gui.color_wheel import ColorWheelDialog
from naga_control.gui.editors import set_lighting
from naga_control.gui.models import ServiceModel
from naga_control.gui.presenter import GuiPresenter
from naga_control.gui.settings_page import ProfileSettingsPage
from naga_control.gui.settings_view import (
    LIGHTING_DIRECTIONS,
    LIGHTING_KINDS,
    LIGHTING_SPEEDS,
    ZONE_LABELS,
    ZONES,
    effect_from_parts,
    effect_payloads,
    format_color,
    parse_color,
    zone_effect_allowed,
    zone_values,
)
from naga_control.gui.worker import Runner


@dataclass
class ZoneRow:
    zone: str
    brightness_spin: QSpinBox
    kind_box: QComboBox
    color_edit: QLineEdit
    color_button: QPushButton
    last_color: QColor
    speed_box: QComboBox
    direction_box: QComboBox


class LightingPage(ProfileSettingsPage):
    """Per-zone brightness, effect, and effect payload editors."""

    def __init__(
        self, presenter: GuiPresenter, model: ServiceModel, run: Runner, *, managed: bool = False
    ) -> None:
        super().__init__(presenter, model, run, managed=managed)
        self.rows: list[ZoneRow] = []
        self._loaded: dict[str, tuple[int, LightingEffect]] = {}
        for zone in ZONES:
            self.rows.append(self._build_zone(zone))
        self._on_model_changed()

    def _build_zone(self, zone: str) -> ZoneRow:
        kinds = [kind for kind in LIGHTING_KINDS if zone_effect_allowed(zone, kind)]
        brightness_spin = QSpinBox()
        brightness_spin.setRange(0, 100)
        brightness_spin.setSuffix(" %")
        brightness_spin.setMaximumWidth(140)
        kind_box = QComboBox()
        kind_box.addItems(kinds)
        kind_box.setMaximumWidth(240)
        color_edit = QLineEdit()
        color_edit.setMaximumWidth(120)
        color_edit.setPlaceholderText("R,G,B")
        color_button = QPushButton("Color wheel...")
        color_button.setMaximumWidth(130)
        color_controls = QHBoxLayout()
        color_controls.setContentsMargins(0, 0, 0, 0)
        color_controls.addWidget(color_edit)
        color_controls.addWidget(color_button)
        color_controls.addStretch()
        speed_box = QComboBox()
        speed_box.addItems([str(speed) for speed in LIGHTING_SPEEDS])
        speed_box.setMaximumWidth(140)
        direction_box = QComboBox()
        direction_box.addItems(LIGHTING_DIRECTIONS)
        direction_box.setMaximumWidth(140)

        row = ZoneRow(
            zone=zone,
            brightness_spin=brightness_spin,
            kind_box=kind_box,
            color_edit=color_edit,
            color_button=color_button,
            last_color=QColor(255, 255, 255),
            speed_box=speed_box,
            direction_box=direction_box,
        )
        group = QFormLayout()
        group.addRow("Brightness", brightness_spin)
        group.addRow("Effect", kind_box)
        group.addRow("Color (R,G,B)", color_controls)
        group.addRow("Speed", speed_box)
        group.addRow("Direction", direction_box)
        self.form.addRow(ZONE_LABELS[zone], group)

        brightness_spin.valueChanged.connect(self._value_changed)
        kind_box.currentTextChanged.connect(partial(self._kind_row_changed, row))
        color_edit.textChanged.connect(partial(self._color_changed, row))
        color_button.clicked.connect(partial(self._open_color_wheel, row))
        speed_box.currentTextChanged.connect(self._text_changed)
        direction_box.currentTextChanged.connect(self._text_changed)
        self._sync_payload_enabled(row)
        return row

    def _load(self, profile: Profile) -> None:
        self._loaded = {}
        for row in self.rows:
            brightness, effect = zone_values(profile, row.zone)
            self._loaded[row.zone] = (brightness, effect)
            row.brightness_spin.blockSignals(True)
            row.brightness_spin.setValue(brightness)
            row.brightness_spin.blockSignals(False)
            row.kind_box.blockSignals(True)
            row.kind_box.setCurrentText(effect.kind)
            row.kind_box.blockSignals(False)
            row.color_edit.blockSignals(True)
            row.color_edit.setText(format_color(effect.color))
            row.color_edit.blockSignals(False)
            self._update_swatch(row)
            row.speed_box.blockSignals(True)
            row.speed_box.setCurrentText(str(effect.speed) if effect.speed else "1")
            row.speed_box.blockSignals(False)
            row.direction_box.blockSignals(True)
            if effect.direction:
                row.direction_box.setCurrentText(effect.direction)
            row.direction_box.blockSignals(False)
            self._sync_payload_enabled(row)

    def _kind_row_changed(self, row: ZoneRow, _text: str) -> None:
        self._sync_payload_enabled(row)
        self._check_dirty()

    def _sync_payload_enabled(self, row: ZoneRow) -> None:
        wants_color, wants_speed, wants_direction = effect_payloads(row.kind_box.currentText())
        row.color_edit.setEnabled(wants_color)
        row.color_button.setEnabled(wants_color)
        row.speed_box.setEnabled(wants_speed)
        row.direction_box.setEnabled(wants_direction)

    def _value_changed(self, _value: int) -> None:
        self._check_dirty()

    def _text_changed(self, _text: str) -> None:
        self._check_dirty()

    def _color_changed(self, row: ZoneRow, _text: str) -> None:
        self._update_swatch(row)
        self._check_dirty()

    def _update_swatch(self, row: ZoneRow) -> None:
        try:
            red, green, blue = parse_color(row.color_edit.text())
        except ConfigValidationError:
            row.color_button.setToolTip("Invalid RGB entry; choosing a color will replace it")
            return
        row.last_color = QColor(red, green, blue)
        swatch = QPixmap(18, 18)
        swatch.fill(row.last_color)
        row.color_button.setIcon(QIcon(swatch))
        row.color_button.setToolTip(f"Choose a color (current: {row.last_color.name()})")

    def _open_color_wheel(self, row: ZoneRow) -> None:
        dialog = ColorWheelDialog(row.last_color, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            color = dialog.color()
            row.color_edit.setText(f"{color.red()},{color.green()},{color.blue()}")

    def _check_dirty(self) -> None:
        try:
            current = self._current_zones()
        except ConfigValidationError:
            self._set_dirty(True)
            return
        self._set_dirty(current != self._loaded)

    def _current_zones(self) -> dict[str, tuple[int, LightingEffect]]:
        result: dict[str, tuple[int, LightingEffect]] = {}
        for row in self.rows:
            color = parse_color(row.color_edit.text()) if row.color_edit.isEnabled() else None
            speed = int(row.speed_box.currentText()) if row.speed_box.isEnabled() else None
            direction = row.direction_box.currentText() if row.direction_box.isEnabled() else None
            effect = effect_from_parts(row.kind_box.currentText(), color, speed, direction)
            result[row.zone] = (row.brightness_spin.value(), effect)
        return result

    def _build_document(self, document: str) -> str:
        zones = self._current_zones()
        lighting = LightingSettings(
            **{
                zone: LightingZone(brightness=brightness, effect=effect)
                for zone, (brightness, effect) in zones.items()
            }
        )
        return set_lighting(
            document, self.profile_id or parse_toml(document).active_profile, lighting
        )
