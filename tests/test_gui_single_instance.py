import os
import subprocess
import sys
from collections.abc import Iterator
from typing import cast
from uuid import uuid4

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import QApplication, QWidget

from naga_control.gui import app as gui_app
from naga_control.gui.single_instance import GuiInstance


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    yield cast(QApplication, app)


def test_relaunch_restores_hidden_and_minimized_window(qapp: QApplication) -> None:
    name = f"naga-control-test-{uuid4().hex}"
    owner = GuiInstance.start(name)
    assert owner is not None
    window = QWidget()
    owner.set_window(window)
    try:
        assert GuiInstance.start(name) is None
        qapp.processEvents()
        assert window.isVisible()

        window.showMinimized()
        qapp.processEvents()
        assert GuiInstance.start(name) is None
        qapp.processEvents()
        assert window.isVisible() and not window.isMinimized()

        window.hide()
        assert GuiInstance.start(name) is None
        qapp.processEvents()
        assert window.isVisible()
    finally:
        owner.close()
        window.close()

    replacement = GuiInstance.start(name)
    assert replacement is not None
    replacement.close()


def test_a_local_connection_is_enough_to_activate_window(qapp: QApplication) -> None:
    name = f"naga-control-test-{uuid4().hex}"
    owner = GuiInstance.start(name)
    assert owner is not None
    window = QWidget()
    owner.set_window(window)
    client = QLocalSocket()
    client.setSocketOptions(QLocalSocket.SocketOption.AbstractNamespaceOption)
    try:
        client.connectToServer(name)
        assert client.waitForConnected(500)
        client.disconnectFromServer()
        qapp.processEvents()
        assert window.isVisible()
    finally:
        client.close()
        owner.close()


def test_second_process_activates_existing_gui(qapp: QApplication) -> None:
    name = f"naga-control-test-{uuid4().hex}"
    owner = GuiInstance.start(name)
    assert owner is not None
    window = QWidget()
    owner.set_window(window)
    try:
        subprocess.run(
            [
                sys.executable,
                "-c",
                "from PySide6.QtWidgets import QApplication; "
                "from naga_control.gui.single_instance import GuiInstance; "
                "app = QApplication([]); assert GuiInstance.start(" + repr(name) + ") is None",
            ],
            check=True,
            timeout=10,
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        )
        qapp.processEvents()
        assert window.isVisible()
    finally:
        owner.close()
        window.close()


def test_main_sets_desktop_identity_before_looking_for_an_instance(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    class FakeApplication:
        @staticmethod
        def setDesktopFileName(name: str) -> None:
            calls.append(f"desktop:{name}")

        def __init__(self, _argv: list[str]) -> None:
            calls.append("application")

        def setWindowIcon(self, _icon: object) -> None:
            pass

        def setQuitOnLastWindowClosed(self, _enabled: bool) -> None:
            pass

    class FakeInstance:
        @staticmethod
        def start() -> None:
            calls.append("instance")

    monkeypatch.setattr(gui_app, "QApplication", FakeApplication)
    monkeypatch.setattr(gui_app, "GuiInstance", FakeInstance)

    assert gui_app.main() == 0
    assert calls == ["desktop:org.nagacontrol.NagaControl", "application", "instance"]
