import asyncio
import os
from collections.abc import Callable, Coroutine, Iterator
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from naga_control.config import dump_toml, parse_toml
from naga_control.domain.actions import MouseButtonAction
from naga_control.domain.defaults import default_configuration
from naga_control.gui.buttons_page import ButtonsPage
from naga_control.gui.models import ServiceModel
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
        self.document = dump_toml(default_configuration())
        self.applied: list[str] = []

    async def snapshot_document(self) -> str:
        return SNAPSHOT

    async def release_all(self) -> None:
        return None

    async def configuration_document(self) -> str:
        return self.document

    async def apply_configuration(self, expected_revision: int, document: str) -> int:
        self.applied.append(document)
        self.document = document
        return parse_toml(document).revision

    async def select_profile(self, profile_id: str) -> int:
        return 1


async def _opened(client: NagaControlClient) -> NagaControlClient:
    return client


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    yield cast(QApplication, app)


def _sync_run(factory: Callable[[], Coroutine[Any, Any, object]]) -> None:
    asyncio.run(factory())


def _page(qapp: QApplication) -> tuple[ButtonsPage, FakeClient]:
    client = FakeClient()
    model = ServiceModel()
    presenter = GuiPresenter(model, open_client=lambda: _opened(client))
    page = ButtonsPage(presenter, model, _sync_run)
    _sync_run(presenter.refresh)
    qapp.processEvents()
    return page, client


def _row(page: ButtonsPage, control_id: str):
    for row in page.rows:
        if row.control_id == control_id:
            return row
    raise AssertionError(f"no row for {control_id}")


def test_page_lists_controls_in_illustration_number_order(qapp: QApplication) -> None:
    page, _client = _page(qapp)

    controls = [row.control_id for row in page.rows]
    assert len(controls) == 7 + 12 + 6 + 2
    assert controls[:7] == [
        "dpi_up",
        "dpi_down",
        "wheel_tilt_left",
        "wheel_tilt_right",
        "top_front",
        "top_rear",
        "ring_finger",
    ]
    assert controls[7:19] == [
        f"side_12_{number}" for number in (3, 6, 9, 12, 2, 5, 8, 11, 1, 4, 7, 10)
    ]
    assert controls[19:25] == [f"side_6_{number}" for number in (1, 2, 3, 6, 5, 4)]
    assert controls[25:] == ["side_2_front", "side_2_rear"]
    assert [int(row.number_label.text()) for row in page.rows] == [3, 4, *range(6, 31)]
    assert page.rows_layout.count() == 31  # Header and all 30 illustration numbers.
    assert _row(page, "top_front").kind_box.currentText() == "passthrough"
    assert not _row(page, "top_front").detail_edit.isEnabled()
    assert not page.apply_button.isEnabled()


def test_changing_an_action_marks_the_page_dirty(qapp: QApplication) -> None:
    page, _client = _page(qapp)

    row = _row(page, "dpi_up")
    row.kind_box.setCurrentText("mouse_button")
    row.detail_edit.setCurrentText("forward")

    assert page.apply_button.isEnabled()
    assert page.status_label.text() == "unsaved changes"


def test_apply_sends_replacement_bindings(qapp: QApplication) -> None:
    page, client = _page(qapp)

    row = _row(page, "dpi_up")
    row.kind_box.setCurrentText("mouse_button")
    row.detail_edit.setCurrentText("forward")
    page.apply_button.click()
    qapp.processEvents()

    document = client.applied[0]
    configuration = parse_toml(document)
    profile = configuration.profile(configuration.active_profile)
    binding = profile.bindings.action_for("dpi_up", profile.plate_layout)
    assert binding == MouseButtonAction(button="forward")
    assert configuration.revision == default_configuration().revision + 1
    assert page.status_label.text() == "applied"
    assert not page.apply_button.isEnabled()


def test_invalid_combo_is_rejected_before_sending(qapp: QApplication) -> None:
    page, client = _page(qapp)

    row = _row(page, "top_front")
    row.kind_box.setCurrentText("key_combo")
    row.detail_edit.setCurrentText("single_key")
    page.apply_button.click()
    qapp.processEvents()

    assert client.applied == []
    assert page.status_label.text().startswith("rejected:")
    assert page.model.apply_status is not None


def test_repeated_applies_do_not_leave_orphan_labels(qapp: QApplication) -> None:
    page, client = _page(qapp)
    for button in ("forward", "back", "middle"):
        row = _row(page, "dpi_up")
        row.kind_box.setCurrentText("mouse_button")
        row.detail_edit.setCurrentText(button)
        page.apply_button.click()
        qapp.processEvents()
        assert page.rows_layout.count() == 31
        assert len(page.rows) == 27
        assert not page.apply_button.isEnabled()
    assert len(client.applied) == 3


def test_mapping_map_click_selects_the_binding_row(qapp: QApplication) -> None:
    from naga_control.gui.mapping_zones import zone_for_control

    page, _client = _page(qapp)
    zone = zone_for_control("dpi_up")
    assert zone is not None

    page.mapping_map.zone_clicked(zone)
    qapp.processEvents()

    selected = _row(page, "dpi_up")
    assert "rgba(68, 255, 136" in selected.root.styleSheet()


def test_mapping_map_shows_current_bindings(qapp: QApplication) -> None:
    page, _client = _page(qapp)

    dpi_up = next(item for item in page.mapping_map.zone_items if item.zone.control_id == "dpi_up")
    assert dpi_up.toolTip().startswith("DPI up — ")


def test_editing_all_plates_preserves_runtime_layout(qapp: QApplication) -> None:
    from naga_control.gui.actions_view import action_for_control
    from naga_control.gui.mapping_zones import all_zones

    page, client = _page(qapp)
    for control in ("side_12_3", "side_6_6", "side_2_rear"):
        row = _row(page, control)
        row.kind_box.setCurrentText("mouse_button")
        row.detail_edit.setCurrentText("middle")
    page.apply_button.click()
    qapp.processEvents()

    configuration = parse_toml(client.document)
    profile = configuration.profile(configuration.active_profile)
    assert profile.plate_layout == 12
    for control in ("side_12_3", "side_6_6", "side_2_rear"):
        assert action_for_control(profile.bindings, control) == MouseButtonAction(button="middle")
        assert _row(page, control).detail_edit.currentText() == "middle"
    for zone in all_zones():
        if zone.control_id is not None:
            page.mapping_map.zone_clicked(zone)
            row = _row(page, zone.control_id)
            assert int(row.number_label.text()) == zone.number
            assert "rgba(68, 255, 136" in row.root.styleSheet()
