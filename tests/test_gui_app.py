import asyncio
import os
from collections.abc import Callable, Coroutine, Iterator
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from naga_control.config import dump_toml
from naga_control.domain.defaults import default_configuration
from naga_control.gui.app import MainWindow
from naga_control.gui.models import ServiceModel
from naga_control.gui.overview_page import OverviewPage
from naga_control.gui.presenter import GuiPresenter
from naga_control.ipc.client import NagaControlClient

SNAPSHOT = '{"status":"available","generation":9,"transport":"hyperspeed","error":null}'


class _NullCalls:
    async def call_get_snapshot(self) -> str:
        raise NotImplementedError

    async def call_release_all(self) -> None:
        raise NotImplementedError

    async def call_get_configuration(self) -> str:
        raise NotImplementedError

    async def call_apply_configuration(self, expected_revision: int, document: str) -> int:
        raise NotImplementedError

    async def call_select_profile(self, profile_id: str) -> int:
        raise NotImplementedError

    async def call_begin_calibration(self) -> bool:
        raise NotImplementedError

    async def call_end_calibration(self) -> bool:
        raise NotImplementedError

        raise NotImplementedError


class FakeClient(NagaControlClient):
    def __init__(self) -> None:
        super().__init__(_NullCalls())
        self.released = False
        self.selected: list[str] = []

    async def snapshot_document(self) -> str:
        return SNAPSHOT

    async def release_all(self) -> None:
        self.released = True

    async def configuration_document(self) -> str:
        return dump_toml(default_configuration())

    async def select_profile(self, profile_id: str) -> int:
        self.selected.append(profile_id)
        return 1


async def _opened(client: NagaControlClient) -> NagaControlClient:
    return client


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    yield cast(QApplication, app)


def _sync_run(factory: Callable[[], Coroutine[Any, Any, object]]) -> None:
    asyncio.run(factory())


def _window(qapp: QApplication) -> tuple[MainWindow, FakeClient]:
    client = FakeClient()
    model = ServiceModel()
    presenter = GuiPresenter(model, open_client=lambda: _opened(client))
    window = MainWindow(presenter, model, _sync_run)
    _sync_run(presenter.refresh)
    qapp.processEvents()
    return window, client


def _overview(window: MainWindow) -> OverviewPage:
    return cast(OverviewPage, window.tabs.widget(0))


def test_overview_reflects_the_model(qapp: QApplication) -> None:
    window, _client = _window(qapp)
    overview = _overview(window)

    assert overview.connection_label.text() == "online"
    assert overview.status_label.text() == "available"
    assert overview.transport_label.text() == "hyperspeed"
    assert overview.generation_label.text() == "9"
    assert overview.revision_label.text() == str(default_configuration().revision)
    assert overview.error_label.text() == "none"
    assert overview.profiles_box.count() > 0


def test_release_button_drives_the_presenter(qapp: QApplication) -> None:
    window, client = _window(qapp)

    _overview(window).release_button.click()
    qapp.processEvents()

    assert client.released


def test_profile_combo_selects_through_the_presenter(qapp: QApplication) -> None:
    window, client = _window(qapp)
    overview = _overview(window)

    first_profile = overview.profiles_box.itemText(0)
    overview.profiles_box.setCurrentIndex(-1)
    overview.profiles_box.setCurrentText(first_profile)
    qapp.processEvents()

    assert client.selected == [first_profile]


def test_model_updates_reach_the_overview_without_user_action(qapp: QApplication) -> None:
    window, _client = _window(qapp)
    overview = _overview(window)

    assert overview.connection_label.text() == "online"

    window.model.mark_unreachable("lost")
    qapp.processEvents()

    assert overview.connection_label.text().startswith("offline: lost")


def test_main_window_hosts_the_dpi_tab(qapp: QApplication) -> None:
    window, _client = _window(qapp)

    assert window.tabs.count() == 7
    assert window.tabs.tabText(1) == "Buttons"
    assert window.tabs.tabText(2) == "DPI"
    assert window.tabs.tabText(3) == "Scroll"
    assert window.tabs.tabText(4) == "Lighting"
    assert window.tabs.tabText(5) == "Power"
    assert window.tabs.tabText(6) == "Profiles"
