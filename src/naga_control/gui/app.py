"""Compact PySide6 shell bound to the Qt-free presenter and model."""

import logging
import sys
from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget

from naga_control.gui.buttons_page import ButtonsPage
from naga_control.gui.dpi_page import DpiPage
from naga_control.gui.lighting_page import LightingPage
from naga_control.gui.models import ServiceModel
from naga_control.gui.overview_page import OverviewPage
from naga_control.gui.power_page import PowerPage
from naga_control.gui.presenter import GuiPresenter
from naga_control.gui.profiles_page import ProfilesPage
from naga_control.gui.scroll_page import ScrollPage
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

    def __init__(self, presenter: GuiPresenter, model: ServiceModel, run: Runner) -> None:
        super().__init__()
        self.presenter = presenter
        self.model = model
        self._tray: TrayIcon | None = None
        self._quit_requested = False

        self.setWindowTitle("Naga Control")
        self.setMinimumWidth(360)
        self.setWindowIcon(QIcon(str(app_icon_path())))

        self.tabs = QTabWidget()
        self.tabs.addTab(OverviewPage(presenter, model, run), "Overview")
        self.tabs.addTab(ButtonsPage(presenter, model, run), "Buttons")
        self.tabs.addTab(DpiPage(presenter, model, run), "DPI")
        self.tabs.addTab(ScrollPage(presenter, model, run), "Scroll")
        self.tabs.addTab(LightingPage(presenter, model, run), "Lighting")
        self.tabs.addTab(PowerPage(presenter, model, run), "Power")
        self.tabs.addTab(ProfilesPage(presenter, model, run), "Profiles")
        self.setCentralWidget(self.tabs)

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(lambda: run(presenter.refresh))
        self._poll_timer.start(10000)

        self._tray = TrayIcon(
            model, toggle_window=self._toggle_visibility, quit_app=self.quit_to_exit
        )
        if not self._tray.available:
            logger.info("system tray unavailable; closing the window will quit")

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
    app = QApplication(sys.argv[:1])
    app.setWindowIcon(QIcon(str(app_icon_path())))
    app.setQuitOnLastWindowClosed(True)
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
    window.show()
    run(presenter.refresh)
    exit_code = app.exec()
    worker.stop()
    return exit_code


def _log_failure(future: Any) -> None:
    exception = future.exception()
    if exception is not None:
        logger.warning("service call failed", exc_info=exception)


if __name__ == "__main__":
    raise SystemExit(main())
