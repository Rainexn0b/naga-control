"""Compact PySide6 shell bound to the Qt-free presenter and model."""

import logging
import sys
from typing import Any, cast

from PySide6.QtCore import QTimer
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
from naga_control.gui.worker import CoroFactory, LoopWorker, Runner
from naga_control.ipc.client import IntrospectableBus, NagaControlClient, connect_service_client
from naga_control.ipc.server import SessionBus, connect_session_bus

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Tabbed host for the service pages; owns no business logic."""

    def __init__(self, presenter: GuiPresenter, model: ServiceModel, run: Runner) -> None:
        super().__init__()
        self.presenter = presenter
        self.model = model

        self.setWindowTitle("Naga Control")
        self.setMinimumWidth(360)

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


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    app = QApplication(sys.argv[:1])
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
