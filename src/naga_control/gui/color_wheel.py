"""Compact hue/saturation picker with a separate value control."""

from math import atan2, cos, degrees, hypot, pi, sin

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class ColorWheel(QWidget):
    """Select hue and saturation; clicks beyond the disc clamp to its rim.

    ``setColor`` is silent. Only mouse selection emits ``colorChanged``;
    achromatic colors retain the previously selected hue for the next drag.
    Colors are opaque RGB (lighting does not use alpha).
    """

    colorChanged = Signal(QColor)
    _SIZE = 160
    _CENTER = _SIZE / 2
    _RADIUS = _CENTER - 1

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(self._SIZE, self._SIZE)
        self._hue = 0
        self._saturation = 255
        self._value = 255
        self._dragging = False
        self._disc = QImage(self._SIZE, self._SIZE, QImage.Format.Format_ARGB32_Premultiplied)
        self._disc.fill(Qt.GlobalColor.transparent)
        for y in range(self._SIZE):
            for x in range(self._SIZE):
                dx = x + 0.5 - self._CENTER
                dy = y + 0.5 - self._CENTER
                distance = hypot(dx, dy)
                if distance <= self._RADIUS:
                    hue = int(degrees(atan2(-dy, dx)) % 360)
                    saturation = round(distance / self._RADIUS * 255)
                    self._disc.setPixel(x, y, QColor.fromHsv(hue, saturation, 255).rgba())

    def color(self) -> QColor:
        return QColor.fromHsv(self._hue, self._saturation, self._value)

    def setColor(self, color: QColor) -> None:
        """Update without emitting, including when called by the value slider."""
        if not color.isValid():
            raise ValueError("color must be valid")
        hue = color.hue()
        if hue >= 0:
            self._hue = hue
        self._saturation = color.saturation()
        self._value = color.value()
        self.update()

    def _select(self, position: QPointF) -> None:
        dx = position.x() - self._CENTER
        dy = position.y() - self._CENTER
        distance = hypot(dx, dy)
        saturation = round(min(distance / self._RADIUS, 1) * 255)
        hue = self._hue if saturation == 0 else int(degrees(atan2(-dy, dx)) % 360)
        if (hue, saturation) != (self._hue, self._saturation):
            self._hue, self._saturation = hue, saturation
            self.update()
            self.colorChanged.emit(self.color())

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._select(event.position())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self._select(event.position())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawImage(0, 0, self._disc)
        angle = self._hue * pi / 180
        radius = min(self._saturation / 255 * self._RADIUS, self._RADIUS - 5)
        marker = QPointF(
            self._CENTER + cos(angle) * radius,
            self._CENTER - sin(angle) * radius,
        )
        painter.setPen(QPen(QColor("#222222"), 3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(marker, 5, 5)
        painter.setPen(QPen(Qt.GlobalColor.white, 2))
        painter.drawEllipse(marker, 4, 4)
        painter.end()


class ColorWheelDialog(QDialog):
    """Edit an RGB color locally; callers apply ``color()`` only on Accepted."""

    def __init__(self, initial: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose color")
        self.setModal(True)

        self.wheel = ColorWheel(self)
        self.wheel.setColor(initial)
        self.value_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.value_slider.setRange(0, 255)
        self.value_slider.setValue(self.wheel.color().value())
        self.swatch = QLabel(self)
        self.swatch.setFixedSize(40, 24)
        self.swatch.setToolTip("Selected color")
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Value", self))
        controls.addWidget(self.value_slider)
        controls.addWidget(self.swatch)
        layout = QVBoxLayout(self)
        layout.addWidget(self.wheel, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addLayout(controls)
        layout.addWidget(self.buttons)

        self.wheel.colorChanged.connect(self._refresh_swatch)
        self.value_slider.valueChanged.connect(self._set_value)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self._refresh_swatch(self.color())

    def color(self) -> QColor:
        return self.wheel.color()

    def _set_value(self, value: int) -> None:
        color = self.wheel.color()
        self.wheel.setColor(
            QColor.fromHsv(color.hue() if color.hue() >= 0 else 0, color.saturation(), value)
        )
        self._refresh_swatch(self.color())

    def _refresh_swatch(self, color: QColor) -> None:
        self.swatch.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #888;")
