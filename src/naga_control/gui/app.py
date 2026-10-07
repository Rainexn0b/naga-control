"""Compact PySide6 shell bound to the Qt-free presenter and model."""

import concurrent.futures
import logging
import sys
from typing import cast

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from naga_control.gui.main_window import MainWindow, app_icon_path
from naga_control.gui.models import ServiceModel
from naga_control.gui.presenter import GuiPresenter
from naga_control.gui.single_instance import GuiInstance
from naga_control.gui.worker import CoroFactory, LoopWorker
from naga_control.ipc.client import IntrospectableBus, NagaControlClient, connect_service_client
from naga_control.ipc.server import SessionBus, connect_session_bus

logger = logging.getLogger(__name__)


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


def _log_failure(future: concurrent.futures.Future[object]) -> None:
    if future.cancelled():
        return
    exception = future.exception()
    if exception is not None:
        logger.warning("service call failed", exc_info=exception)


if __name__ == "__main__":
    raise SystemExit(main())
