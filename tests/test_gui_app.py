import asyncio
import json
import os
from collections.abc import Callable, Coroutine, Iterator
from dataclasses import replace
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from naga_control.config import dump_toml, parse_toml
from naga_control.domain.defaults import default_configuration
from naga_control.gui.app import MainWindow
from naga_control.gui.editors import duplicate_profile
from naga_control.gui.models import ServiceModel
from naga_control.gui.overview_page import OverviewPage
from naga_control.gui.presenter import GuiPresenter
from naga_control.ipc.client import NagaControlClient

SNAPSHOT = json.dumps(
    {
        "status": "available",
        "generation": 9,
        "transport": "hyperspeed",
        "error": None,
        "desired_mode": "software",
        "observed_mode": "software",
        "mode_ready": True,
        "mode_error": None,
        "calibrating": False,
    }
)


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
        self.document = dump_toml(default_configuration())

    async def snapshot_document(self) -> str:
        return SNAPSHOT

    async def release_all(self) -> None:
        self.released = True

    async def configuration_document(self) -> str:
        return self.document

    async def select_profile(self, profile_id: str) -> int:
        self.selected.append(profile_id)
        configuration = parse_toml(self.document)
        configuration = replace(
            configuration, active_profile=profile_id, revision=configuration.revision + 1
        )
        self.document = dump_toml(configuration)
        return configuration.revision


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
    window._poll_timer.stop()  # pyright: ignore[reportPrivateUsage]
    _sync_run(presenter.refresh)
    qapp.processEvents()
    return window, client


def _overview(window: MainWindow) -> OverviewPage:
    return window.device.overview


def _profiles(window: MainWindow):  # pyright: ignore[reportUnknownParameterType]
    return window.device.profiles


def test_overview_reflects_the_model(qapp: QApplication) -> None:
    window, _client = _window(qapp)
    overview = _overview(window)

    assert overview.connection_label.text() == "online"
    assert overview.status_label.text() == "Active (software mode verified)"
    assert overview.transport_label.text() == "hyperspeed"
    assert overview.generation_label.text() == "9"
    assert overview.revision_label.text() == str(default_configuration().revision)
    assert overview.error_label.text() == "none"
    assert not hasattr(window, "profiles_box")
    assert not hasattr(window, "profile_selector_label")
    page = _profiles(window)
    assert page.profiles_box.count() > 0
    assert page.active_label.text().endswith(f"({default_configuration().active_profile})")
    assert _client.selected == []


def test_release_button_drives_the_presenter(qapp: QApplication) -> None:
    window, client = _window(qapp)

    _overview(window).release_button.click()
    qapp.processEvents()

    assert client.released


def test_dropdown_selection_manages_without_activating(qapp: QApplication) -> None:
    window, client = _window(qapp)
    _add_second_profile(window, client, qapp)
    page = _profiles(window)
    assert page.profiles_box.findData("mmo") != -1
    page.profiles_box.setCurrentIndex(page.profiles_box.findData("mmo"))
    qapp.processEvents()

    assert client.selected == []
    assert page.active_label.text().endswith(f"({default_configuration().active_profile})")
    assert page.profiles_box.currentData() == "mmo"
    page.activate_button.click()
    qapp.processEvents()
    assert client.selected == ["mmo"]
    assert page.active_label.text().endswith("(mmo)")


def test_model_updates_reach_the_overview_without_user_action(qapp: QApplication) -> None:
    window, _client = _window(qapp)
    overview = _overview(window)

    assert overview.connection_label.text() == "online"

    window.model.mark_unreachable("lost")
    qapp.processEvents()

    assert overview.connection_label.text().startswith("offline: lost")


def test_main_window_has_three_consolidated_tabs(qapp: QApplication) -> None:
    window, _client = _window(qapp)

    assert window.tabs.count() == 3
    assert window.tabs.tabText(0) == "Device"
    assert window.tabs.tabText(1) == "Buttons"
    assert window.tabs.tabText(2) == "Settings"


def test_opening_size_is_balanced_and_fits_screen(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QScreen

    def desktop_geometry(_screen: QScreen) -> QRect:
        return QRect(0, 0, 1600, 900)

    monkeypatch.setattr(QScreen, "availableGeometry", desktop_geometry)
    window, _client = _window(qapp)
    window.show()
    qapp.processEvents()
    available = window.screen().availableGeometry()

    assert 1.85 < window.width() / window.height() < 2.05
    assert window.width() == pytest.approx(1600 * 0.9 * 0.75, abs=1)
    assert window.height() == pytest.approx(1600 * 0.9 * 0.75 * 660 / 1280, abs=1)
    assert window.width() <= available.width()
    assert window.height() <= available.height()


def test_opening_size_fits_small_screen(qapp: QApplication) -> None:
    window, _client = _window(qapp)
    window.show()
    qapp.processEvents()
    available = window.screen().availableGeometry()

    assert window.width() <= available.width()
    assert window.height() <= available.height()


def test_software_dropdown_fits_360_pixels_with_duplicate_names(qapp: QApplication) -> None:
    window, client = _window(qapp)
    base = parse_toml(client.document)
    profile = replace(base.profile(base.active_profile), display_name="Same")
    client.document = dump_toml(
        replace(
            base,
            active_profile="first",
            default_profile="first",
            profiles=(("first", profile), ("second", profile)),
        )
    )
    _sync_run(window.presenter.refresh)
    qapp.processEvents()
    page = _profiles(window)
    window.resize(360, 660)
    window.show()
    qapp.processEvents()
    assert window.minimumWidth() == 360
    assert window.width() == 360
    assert [page.profiles_box.itemText(i) for i in range(page.profiles_box.count())] == [
        "Same (first)",
        "Same (second)",
    ]
    assert [page.profiles_box.itemData(i) for i in range(page.profiles_box.count())] == [
        "first",
        "second",
    ]
    assert page.profiles_box.fontMetrics().horizontalAdvance("Same (second)") + 60 <= 360
    assert client.selected == []
    assert page.active_label.text() == "Active: Same (first)"
    page.profiles_box.setCurrentIndex(page.profiles_box.findData("second"))
    qapp.processEvents()
    assert client.selected == []
    assert page.active_label.text() == "Active: Same (first)"
    page.activate_button.click()
    qapp.processEvents()
    assert client.selected == ["second"]
    assert page.active_label.text() == "Active: Same (second)"
    assert window.width() == 360
    window.deleteLater()
    qapp.processEvents()


def test_buttons_splitter_gives_more_room_to_artwork(qapp: QApplication) -> None:
    from naga_control.gui.buttons_page import ButtonsPage

    window, _client = _window(qapp)
    window.resize(1600, 820)
    window.tabs.setCurrentIndex(1)
    window.show()
    qapp.processEvents()
    buttons = cast(ButtonsPage, window.tabs.widget(1))
    artwork, editors = buttons.splitter.sizes()

    assert 1.3 < artwork / editors < 1.7


def _add_second_profile(window: MainWindow, client: FakeClient, qapp: QApplication) -> None:
    client.document = duplicate_profile(
        client.document, default_configuration().active_profile, "mmo", "MMO"
    )
    _sync_run(window.presenter.refresh)
    qapp.processEvents()


def test_unified_selector_tracks_external_change_without_writing(qapp: QApplication) -> None:
    window, client = _window(qapp)
    _add_second_profile(window, client, qapp)
    page = _profiles(window)
    page.profiles_box.setCurrentIndex(page.profiles_box.findData("mmo"))
    qapp.processEvents()
    configuration = parse_toml(client.document)
    client.document = dump_toml(
        replace(configuration, active_profile="mmo", revision=configuration.revision + 1)
    )
    _sync_run(window.presenter.refresh)
    qapp.processEvents()

    assert page.active_label.text().endswith("(mmo)")
    assert client.selected == []


@pytest.mark.parametrize("editor", ["settings", "buttons", "power", "plate"])
@pytest.mark.parametrize("discard", [False, True])
def test_profile_activation_warns_about_unsaved_edits(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, editor: str, discard: bool
) -> None:
    window, client = _window(qapp)
    _add_second_profile(window, client, qapp)
    page = _profiles(window)
    if editor == "settings":
        window.settings.dpi.rows[0].x_spin.setValue(3200)
    elif editor == "buttons":
        window.buttons.rows[0].kind_box.setCurrentText("mouse_button")
    elif editor == "power":
        window.device.power.idle_spin.setValue(600)
    else:
        page.plate_box.setCurrentIndex(page.plate_box.findData(6))
    prompts: list[str] = []

    def answer(*args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        prompts.append(str(args[2]))
        return QMessageBox.StandardButton.Yes if discard else QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", answer)
    page.profiles_box.setCurrentIndex(page.profiles_box.findData("mmo"))
    qapp.processEvents()
    assert prompts == []
    assert client.selected == []
    page.activate_button.click()
    qapp.processEvents()

    assert len(prompts) == 1
    assert client.selected == (["mmo"] if discard else [])
    editors = (window.settings, window.buttons, window.device)
    assert any(page.has_unsaved_changes() for page in editors) == (not discard)
