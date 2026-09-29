"""System tray icon with a battery percentage overlay."""

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from naga_control.gui.models import ServiceModel

logger = logging.getLogger(__name__)

TRAY_ICON_SIZE = 128
OVERLAY_MAX_RATIO = 0.82


def tray_icon_path() -> Path:
    """Return the bundled tray icon path for wheel and AppImage layouts."""
    return Path(__file__).resolve().parent / "assets" / "tray.png"


def overlay_battery(base: QImage, percent: int) -> QImage:
    """Paint the battery percentage across the bottom half of the icon."""
    size = base.width()
    overlay = QImage(base)
    painter = QPainter(overlay)
    banner_height = size // 2
    banner_top = size - banner_height

    banner = QRectF(0, banner_top, size, banner_height)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, 190))
    painter.drawRect(banner)

    font = QFont()
    font.setBold(True)
    font.setPixelSize(int(banner_height * OVERLAY_MAX_RATIO))
    painter.setFont(font)
    painter.setPen(QColor(255, 255, 255, 255))
    painter.drawText(banner, Qt.AlignmentFlag.AlignCenter, str(percent))
    painter.end()
    return overlay


class TrayIcon(QObject):
    """Own the QSystemTrayIcon; hide the window into the tray on close."""

    model_changed = Signal()

    def __init__(
        self,
        model: ServiceModel,
        *,
        toggle_window: Callable[[], None],
        quit_app: Callable[[], None],
    ) -> None:
        super().__init__()
        self.model = model
        self._toggle_window = toggle_window
        self._base = QImage(str(tray_icon_path()))
        if self._base.isNull():
            logger.warning("tray icon %s could not be loaded", tray_icon_path())

        self.icon = QSystemTrayIcon(self)
        menu = QMenu()
        show_action = QAction("Show Naga Control", menu)
        quit_action = QAction("Quit", menu)
        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.icon.setContextMenu(menu)

        show_action.triggered.connect(lambda: self._toggle_window())
        quit_action.triggered.connect(quit_app)
        self.icon.activated.connect(self._on_activated)

        self.model.add_listener(self.model_changed.emit)
        self.model_changed.connect(self._update_from_model, Qt.ConnectionType.QueuedConnection)
        self._update_from_model()
        self.icon.show()

    @property
    def available(self) -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._toggle_window()

    def _update_from_model(self) -> None:
        snapshot = self.model.snapshot
        status = snapshot.status if snapshot else "unknown"
        transport = f" · {snapshot.transport}" if snapshot and snapshot.transport else ""
        battery = snapshot.observed.battery_percent if snapshot else None
        charging = snapshot.observed.charging if snapshot else False
        if battery is not None:
            overlay = overlay_battery(self._base, round(battery))
            self.icon.setIcon(QIcon(QPixmap.fromImage(overlay)))
            bolt = " (charging)" if charging else ""
            self.icon.setToolTip(f"Naga Control — {status}{transport} · {round(battery)}%{bolt}")
        else:
            self.icon.setIcon(QIcon(QPixmap.fromImage(self._base)))
            self.icon.setToolTip(f"Naga Control — {status}{transport}")
