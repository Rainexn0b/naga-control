"""Show the existing GUI instead of creating another window on Linux."""

import os

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QWidget


def _request_show(name: str) -> bool:
    socket = QLocalSocket()
    socket.setSocketOptions(QLocalSocket.SocketOption.AbstractNamespaceOption)
    socket.connectToServer(name)
    if not socket.waitForConnected(250):
        return False
    socket.disconnectFromServer()
    return True


class GuiInstance(QObject):
    """Own one per-user abstract socket for the lifetime of the GUI."""

    def __init__(self, server: QLocalServer) -> None:
        super().__init__()
        self._server = server
        server.setParent(self)
        self._window: QWidget | None = None
        server.newConnection.connect(self._receive)

    @classmethod
    def start(cls, name: str | None = None) -> "GuiInstance | None":
        name = name or f"org.nagacontrol.NagaControl-gui-{os.getuid()}"
        if _request_show(name):
            return None
        server = QLocalServer()
        server.setSocketOptions(QLocalServer.SocketOption.AbstractNamespaceOption)
        if server.listen(name):
            return cls(server)
        if _request_show(name):
            return None
        raise RuntimeError(
            f"could not establish the Naga Control GUI instance: {server.errorString()}"
        )

    def set_window(self, window: QWidget) -> None:
        self._window = window

    def close(self) -> None:
        self._server.close()

    def _receive(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.deleteLater()
            if self._window is not None:
                if self._window.isMinimized():
                    self._window.showNormal()
                elif not self._window.isVisible():
                    self._window.show()
                self._window.raise_()
                self._window.activateWindow()
