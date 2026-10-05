"""Compact PySide6 shell bound to the Qt-free presenter and model."""

import logging
import sys
from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from naga_control.config import parse_toml
from naga_control.domain.errors import ConfigValidationError
from naga_control.domain.profiles import ScrollMode
from naga_control.gui.buttons_page import ButtonsPage
from naga_control.gui.device_page import DevicePage
from naga_control.gui.editors import set_scroll
from naga_control.gui.models import ServiceModel
from naga_control.gui.mouse_settings_page import MouseSettingsPage
from naga_control.gui.presenter import ApplyOutcome, GuiPresenter
from naga_control.gui.single_instance import GuiInstance
from naga_control.gui.tray_icon import TrayIcon
from naga_control.gui.worker import CoroFactory, LoopWorker, Runner
from naga_control.ipc.client import IntrospectableBus, NagaControlClient, connect_service_client
from naga_control.ipc.server import SessionBus, connect_session_bus

logger = logging.getLogger(__name__)


def app_icon_path() -> Path:
    """Return the bundled application icon for taskbar and window entries."""
    return Path(__file__).resolve().parent / "assets" / "start.png"


class MainWindow(QMainWindow):
    """Tabbed host for the service pages; owns no business logic."""

    model_changed = Signal()
    profile_switch_finished = Signal(object)
    scroll_change_finished = Signal(object)

    def __init__(self, presenter: GuiPresenter, model: ServiceModel, run: Runner) -> None:
        super().__init__()
        self.presenter = presenter
        self.model = model
        self._run = run
        self._tray: TrayIcon | None = None
        self._quit_requested = False
        self._profile_switching = False
        self._profile_discard_pending = False
        self._scroll_switching = False
        self.profile_switch_finished.connect(
            self._finish_profile_switch, Qt.ConnectionType.QueuedConnection
        )
        self.scroll_change_finished.connect(
            self._finish_scroll_change, Qt.ConnectionType.QueuedConnection
        )

        self.setWindowTitle("Naga Control")
        self.setMinimumWidth(360)
        self.setWindowIcon(QIcon(str(app_icon_path())))

        self.tabs = QTabWidget()
        self.device = DevicePage(presenter, model, run)
        self.buttons = ButtonsPage(presenter, model, run)
        self.settings = MouseSettingsPage(presenter, model, run)
        self.device.profiles.confirm_profile_change = self._confirm_and_discard
        self.tabs.addTab(self.device, "Device")
        self.tabs.addTab(self.buttons, "Buttons")
        self.tabs.addTab(self.settings, "Settings")
        self.profiles_box = QComboBox()
        self.profiles_box.setMaximumWidth(260)
        self.profiles_box.currentIndexChanged.connect(self._profile_selected)
        header = QHBoxLayout()
        header.addWidget(QLabel("Naga V3 Pro"))
        header.addStretch()
        header.addWidget(QLabel("Active profile"))
        header.addWidget(self.profiles_box)
        central = QWidget()
        column = QVBoxLayout(central)
        column.addLayout(header)
        column.addWidget(self.tabs)
        self.setCentralWidget(central)
        self.model.add_listener(self.model_changed.emit)
        self.model_changed.connect(self._update_header, Qt.ConnectionType.QueuedConnection)
        self._update_header()
        opening_size = QSize(1280, 660)
        available = self.screen().availableGeometry()
        opening_size.scale(
            QSize(int(available.width() * 0.9), int(available.height() * 0.9)),
            Qt.AspectRatioMode.KeepAspectRatio,
        )
        self.resize(opening_size * 0.75)

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(lambda: run(presenter.refresh))
        self._poll_timer.start(10000)

        self._tray = TrayIcon(
            model,
            toggle_window=self._toggle_visibility,
            select_profile=self._request_profile,
            change_scroll=self._request_scroll,
            quit_app=self.quit_to_exit,
        )
        if not self._tray.available:
            logger.info("system tray unavailable; closing the window will quit")

    def _update_header(self) -> None:
        self.statusBar().showMessage(self.model.apply_status or "")
        document = self.model.configuration_document
        if document is None:
            self.profiles_box.setEnabled(False)
            return
        try:
            configuration = parse_toml(document)
        except ConfigValidationError:
            self.profiles_box.setEnabled(False)
            return
        self.profiles_box.blockSignals(True)
        self.profiles_box.clear()
        for identifier, profile in configuration.profiles:
            self.profiles_box.addItem(profile.display_name, identifier)
        self.profiles_box.setCurrentIndex(self.profiles_box.findData(configuration.active_profile))
        self.profiles_box.blockSignals(False)
        self.profiles_box.setEnabled(
            self.model.connection.reachable
            and self.model.apply_status != "applying…"
            and not self._profile_switching
            and not self._scroll_switching
        )

    def _confirm_discard(self) -> bool:
        editors = (self.device, self.buttons, self.settings)
        if not any(editor.has_unsaved_changes() for editor in editors):
            return True
        answer = QMessageBox.question(
            self if self.isVisible() else None,
            "Unsaved changes",
            "Discard unsaved edits before changing profiles?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _confirm_and_discard(self) -> bool:
        if not self._confirm_discard():
            return False
        for editor in (self.device, self.buttons, self.settings):
            editor.discard_changes()
        return True

    def _profile_selected(self, _index: int) -> None:
        profile_id = self.profiles_box.currentData()
        if isinstance(profile_id, str):
            self._request_profile(profile_id)

    def _request_profile(self, profile_id: str) -> None:
        document = self.model.configuration_document
        if (
            self._profile_switching
            or self._scroll_switching
            or not self.model.connection.reachable
            or document is None
        ):
            self._update_header()
            return
        try:
            configuration = parse_toml(document)
        except ConfigValidationError:
            self._update_header()
            return
        if profile_id == configuration.active_profile or profile_id not in {
            identifier for identifier, _ in configuration.profiles
        }:
            self._update_header()
            return
        if not self._confirm_discard():
            self._update_header()
            return
        self._profile_discard_pending = any(
            editor.has_unsaved_changes() for editor in (self.device, self.buttons, self.settings)
        )
        self._profile_switching = True
        if self._tray is not None:
            self._tray.set_profile_switching(True)
        for editor in (self.device, self.buttons, self.settings):
            editor.setEnabled(False)
        self.profiles_box.setEnabled(False)
        self.model.set_apply_status("Switching profile...")
        self._run(lambda: self._select_profile(profile_id))

    async def _select_profile(self, profile_id: str) -> None:
        outcome = await self.presenter.select_profile(profile_id)
        self.model.set_apply_status(
            "Profile switched" if outcome is ApplyOutcome.APPLIED else "Profile switch failed"
        )
        self.profile_switch_finished.emit(outcome)

    def _finish_profile_switch(self, outcome: ApplyOutcome) -> None:
        self._profile_switching = False
        if outcome is ApplyOutcome.APPLIED and self._profile_discard_pending:
            for editor in (self.device, self.buttons, self.settings):
                editor.discard_changes()
        self._profile_discard_pending = False
        if self._tray is not None:
            self._tray.set_profile_switching(False)
        for editor in (self.device, self.buttons, self.settings):
            editor.setEnabled(True)
        self._update_header()

    def _request_scroll(
        self,
        mode: ScrollMode | None,
        acceleration: bool | None,
        smart_reel: bool | None,
    ) -> None:
        document = self.model.configuration_document
        if (
            self._scroll_switching
            or self._profile_switching
            or self.model.apply_status == "applying…"
            or not self.model.connection.reachable
            or document is None
        ):
            return
        try:
            configuration = parse_toml(document)
            profile = configuration.profile(configuration.active_profile)
            current = profile.scroll
            updated = set_scroll(
                document,
                configuration.active_profile,
                mode if mode is not None else current.mode,
                acceleration if acceleration is not None else current.acceleration,
                smart_reel if smart_reel is not None else current.smart_reel,
            )
        except ConfigValidationError:
            self.model.set_apply_status("Invalid scroll settings")
            return
        if self.settings.profile_id == configuration.active_profile and (
            self.settings.scroll_section.has_unsaved_changes()
        ):
            answer = QMessageBox.question(
                self if self.isVisible() else None,
                "Unsaved scroll changes",
                "Replace unsaved Scroll edits if the tray shortcut saves successfully?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._scroll_switching = True
        if self._tray is not None:
            self._tray.set_scroll_switching(True)
        for editor in (self.device, self.buttons, self.settings):
            editor.setEnabled(False)
        self.profiles_box.setEnabled(False)
        self.model.set_apply_status("Saving scroll settings...")
        self._run(lambda: self._apply_scroll(updated))

    async def _apply_scroll(self, document: str) -> None:
        outcome = await self.presenter.apply_configuration(document)
        if outcome is ApplyOutcome.APPLIED:
            await self.presenter.refresh()
        self.model.set_apply_status(
            {
                ApplyOutcome.APPLIED: (
                    "Scroll settings saved; hardware status may update later"
                    if self.model.connection.reachable
                    else "Scroll settings saved; hardware status unavailable"
                ),
                ApplyOutcome.STALE: "Scroll settings changed on the service; retry",
                ApplyOutcome.INVALID: "Scroll settings rejected",
                ApplyOutcome.UNREACHABLE: "Service unreachable",
            }[outcome]
        )
        self.scroll_change_finished.emit(outcome)

    def _finish_scroll_change(self, outcome: ApplyOutcome) -> None:
        self._scroll_switching = False
        if outcome is ApplyOutcome.APPLIED and self.settings.profile_id:
            document = self.model.configuration_document
            if document is not None:
                configuration = parse_toml(document)
                if self.settings.profile_id == configuration.active_profile:
                    self.settings.scroll_section.load_profile(
                        configuration.active_profile,
                        configuration.profile(configuration.active_profile),
                    )
        if self._tray is not None:
            self._tray.set_scroll_switching(False)
        for editor in (self.device, self.buttons, self.settings):
            editor.setEnabled(True)
        self._update_header()

    def _toggle_visibility(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def closeEvent(self, event: Any) -> None:
        if self._tray is not None and self._tray.available and not self._quit_requested:
            event.ignore()
            self.hide()
            return
        super().closeEvent(event)

    def quit_to_exit(self) -> None:
        self._quit_requested = True
        self.close()
        application = QApplication.instance()
        if application is not None:
            application.quit()


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    QApplication.setDesktopFileName("org.nagacontrol.NagaControl")
    app = QApplication(sys.argv[:1])
    app.setWindowIcon(QIcon(str(app_icon_path())))
    app.setQuitOnLastWindowClosed(True)
    instance = GuiInstance.start()
    if instance is None:
        return 0
    worker = LoopWorker()
    worker.start()

    def run(factory: CoroFactory) -> None:
        future = worker.submit(factory)
        future.add_done_callback(_log_failure)

    bus_holders: list[SessionBus] = []

    async def open_client() -> NagaControlClient:
        bus = await connect_session_bus()
        bus_holders.append(bus)
        return await connect_service_client(cast(IntrospectableBus, bus))

    def close_client(client: object) -> None:
        for bus in bus_holders:
            bus.disconnect()
        bus_holders.clear()

    model = ServiceModel()
    presenter = GuiPresenter(model, open_client=open_client, close_client=close_client)
    window = MainWindow(presenter, model, run)
    instance.set_window(window)
    window.show()
    run(presenter.refresh)
    exit_code = app.exec()
    worker.stop()
    instance.close()
    return exit_code


def _log_failure(future: Any) -> None:
    if future.cancelled():
        return
    exception = future.exception()
    if exception is not None:
        logger.warning("service call failed", exc_info=exception)


if __name__ == "__main__":
    raise SystemExit(main())
