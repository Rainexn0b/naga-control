"""System tray icon with a battery percentage overlay."""

import logging
from collections.abc import Callable
from functools import partial
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from naga_control.config import parse_toml
from naga_control.domain.errors import ConfigValidationError
from naga_control.domain.profiles import ScrollMode
from naga_control.gui.models import ServiceModel
from naga_control.gui.settings_view import SCROLL_MODES

logger = logging.getLogger(__name__)

TRAY_ICON_SIZE = 128
OVERLAY_MAX_RATIO = 0.82
_SCROLL_LABELS: dict[str, str] = {
    "tactile": "Tactile",
    "free_spin": "Free spin",
    "precision_tactile": "Precision tactile",
}


def tray_icon_path() -> Path:
    """Return the bundled tray icon path for wheel and AppImage layouts."""
    return Path(__file__).resolve().parent / "assets" / "tray.png"


def overlay_battery(base: QImage, percent: int) -> QImage:
    """Paint the battery percentage across the bottom half of the icon."""
    size = base.width()
    overlay = QImage(base)
    painter = QPainter(overlay)
    banner_height = size // 2
    banner = QRectF(0, size - banner_height, size, banner_height)

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
        select_profile: Callable[[str], None],
        change_scroll: Callable[[ScrollMode | None, bool | None, bool | None], None],
        quit_app: Callable[[], None],
    ) -> None:
        super().__init__()
        self.model = model
        self._toggle_window = toggle_window
        self._select_profile = select_profile
        self._change_scroll = change_scroll
        self._switching = False
        self._scroll_switching = False
        self._profile_document: str | None = None
        self.profile_actions: dict[str, QAction] = {}
        self._base = QImage(str(tray_icon_path()))
        if self._base.isNull():
            logger.warning("tray icon %s could not be loaded", tray_icon_path())

        self.icon = QSystemTrayIcon(self)
        self.menu = QMenu()
        self.show_action = self.menu.addAction("Show Naga Control")
        self.profile_menu = self.menu.addMenu("Active profile")
        self.profile_group = QActionGroup(self.profile_menu)
        self.profile_group.setExclusive(True)
        self.scroll_menu = self.menu.addMenu("Scroll wheel")
        self.scroll_group = QActionGroup(self.scroll_menu)
        self.scroll_group.setExclusive(True)
        self.scroll_actions: dict[ScrollMode, QAction] = {}
        for mode in SCROLL_MODES:
            action = self.scroll_menu.addAction(_SCROLL_LABELS[mode])
            action.setCheckable(True)
            self.scroll_group.addAction(action)
            action.triggered.connect(partial(self._scroll_mode_requested, mode))
            self.scroll_actions[mode] = action
        self.scroll_menu.addSeparator()
        self.acceleration_action = self.scroll_menu.addAction("Acceleration")
        self.acceleration_action.setCheckable(True)
        self.acceleration_action.triggered.connect(self._scroll_acceleration_requested)
        self.smart_reel_action = self.scroll_menu.addAction("Smart Reel")
        self.smart_reel_action.setCheckable(True)
        self.smart_reel_action.triggered.connect(self._scroll_smart_reel_requested)
        self.scroll_menu.addSeparator()
        self.observed_scroll_action = self.scroll_menu.addAction("Observed mode: unknown")
        self.observed_scroll_action.setEnabled(False)
        self.scroll_failure_action = self.scroll_menu.addAction("")
        self.scroll_failure_action.setEnabled(False)
        self.scroll_failure_action.setVisible(False)
        self.menu.addSeparator()
        self.quit_action = self.menu.addAction("Quit")
        self.icon.setContextMenu(self.menu)

        self.show_action.triggered.connect(lambda: self._toggle_window())
        self.quit_action.triggered.connect(quit_app)
        self.icon.activated.connect(self._on_activated)
        self.menu.aboutToShow.connect(self._update_profiles)
        self.profile_menu.aboutToShow.connect(lambda: self._update_profiles(force=True))
        self.profile_menu.aboutToHide.connect(lambda: QTimer.singleShot(0, self._update_profiles))
        self.menu.aboutToShow.connect(self._update_scroll)
        self.scroll_menu.aboutToShow.connect(self._update_scroll)

        self.model.add_listener(self.model_changed.emit)
        self.model_changed.connect(self._update_from_model, Qt.ConnectionType.QueuedConnection)
        self._update_from_model()
        self.icon.show()

    @property
    def available(self) -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def set_profile_switching(self, switching: bool) -> None:
        self._switching = switching
        self._update_profiles()
        self._update_scroll()

    def set_scroll_switching(self, switching: bool) -> None:
        self._scroll_switching = switching
        self._update_profiles()
        self._update_scroll()

    def _scroll_mode_requested(self, mode: ScrollMode, _checked: bool = False) -> None:
        self._scroll_requested(mode=mode)

    def _scroll_acceleration_requested(self, checked: bool) -> None:
        self._scroll_requested(acceleration=checked)

    def _scroll_smart_reel_requested(self, checked: bool) -> None:
        self._scroll_requested(smart_reel=checked)

    def _scroll_requested(
        self,
        mode: ScrollMode | None = None,
        acceleration: bool | None = None,
        smart_reel: bool | None = None,
    ) -> None:
        document = self.model.configuration_document
        try:
            configuration = parse_toml(document) if document is not None else None
        except ConfigValidationError:
            configuration = None
        if (
            configuration is not None
            and self.model.connection.reachable
            and not self._switching
            and not self._scroll_switching
            and self.model.apply_status != "applying…"
        ):
            current = configuration.profile(configuration.active_profile).scroll
            if (
                (mode is not None and mode != current.mode)
                or (acceleration is not None and acceleration != current.acceleration)
                or (smart_reel is not None and smart_reel != current.smart_reel)
            ):
                self._change_scroll(mode, acceleration, smart_reel)
        self._update_scroll()

    def _update_scroll(self) -> None:
        document = self.model.configuration_document
        try:
            configuration = parse_toml(document) if document is not None else None
        except ConfigValidationError:
            configuration = None
        if configuration is not None:
            scroll = configuration.profile(configuration.active_profile).scroll
            for mode, action in self.scroll_actions.items():
                action.setChecked(mode == scroll.mode)
            self.acceleration_action.setChecked(scroll.acceleration)
            self.smart_reel_action.setChecked(scroll.smart_reel)
        else:
            for action in (
                *self.scroll_actions.values(),
                self.acceleration_action,
                self.smart_reel_action,
            ):
                action.setChecked(False)
        snapshot = self.model.snapshot if self.model.connection.reachable else None
        observed = (
            snapshot.observed if snapshot is not None and snapshot.status == "available" else None
        )
        observed_mode = observed.scroll_mode if observed is not None else None
        self.observed_scroll_action.setText(
            f"Observed mode: {_SCROLL_LABELS.get(observed_mode or '', observed_mode or 'unknown')}"
        )
        acceleration = observed.scroll_acceleration if observed is not None else None
        smart_reel = observed.scroll_smart_reel if observed is not None else None
        self.observed_scroll_action.setToolTip(
            "Observed hardware: "
            + f"acceleration {self._observed_flag(acceleration)}, "
            + f"Smart Reel {self._observed_flag(smart_reel)}"
        )
        failures = (
            [
                failure
                for failure in snapshot.observed.settings_failures
                if failure.startswith(("scroll_", "profile:"))
            ]
            if snapshot is not None
            else []
        )
        if snapshot is not None and snapshot.status != "available" and not failures:
            failures = [snapshot.status]
        self.scroll_failure_action.setText("Hardware error: " + "; ".join(failures))
        self.scroll_failure_action.setVisible(bool(failures))
        self.scroll_menu.setEnabled(
            configuration is not None
            and self.model.connection.reachable
            and not self._switching
            and not self._scroll_switching
            and self.model.apply_status != "applying…"
        )

    @staticmethod
    def _observed_flag(value: bool | None) -> str:
        return "unknown" if value is None else "on" if value else "off"

    def _profile_requested(self, profile_id: str) -> None:
        document = self.model.configuration_document
        try:
            configuration = parse_toml(document) if document is not None else None
        except ConfigValidationError:
            configuration = None
        if (
            not self.model.connection.reachable
            or self._switching
            or self.model.apply_status == "applying…"
            or configuration is None
            or profile_id not in {identifier for identifier, _ in configuration.profiles}
        ):
            self._update_profiles()
            return
        if profile_id != configuration.active_profile:
            self._select_profile(profile_id)
        self._update_profiles()

    def _update_profiles(self, *, force: bool = False) -> None:
        document = self.model.configuration_document
        try:
            configuration = parse_toml(document) if document is not None else None
        except ConfigValidationError:
            configuration = None
        if configuration is None:
            self.profile_menu.setEnabled(False)
            return
        if document != self._profile_document and (force or not self.profile_menu.isVisible()):
            for action in self.profile_actions.values():
                self.profile_group.removeAction(action)
            self.profile_menu.clear()
            self.profile_actions.clear()
            self._profile_document = document
            for identifier, profile in configuration.profiles:
                action = self.profile_menu.addAction(f"{profile.display_name} ({identifier})")
                action.setCheckable(True)
                self.profile_group.addAction(action)
                action.triggered.connect(
                    lambda _checked=False, key=identifier: self._profile_requested(key)
                )
                self.profile_actions[identifier] = action
        for identifier, action in self.profile_actions.items():
            action.setChecked(identifier == configuration.active_profile)
        self.profile_menu.setEnabled(
            self.model.connection.reachable
            and not self._switching
            and not self._scroll_switching
            and self.model.apply_status != "applying…"
        )

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._toggle_window()

    def _update_from_model(self) -> None:
        self._update_profiles()
        self._update_scroll()
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
