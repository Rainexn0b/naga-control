import asyncio
import os
from collections.abc import Callable, Coroutine, Iterator
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from naga_control.config import dump_toml, parse_toml
from naga_control.domain.defaults import default_configuration
from naga_control.gui.dpi_page import DpiPage
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
        self.applied: list[tuple[int, str]] = []

    async def snapshot_document(self) -> str:
        return SNAPSHOT

    async def release_all(self) -> None:
        return None

    async def configuration_document(self) -> str:
        return self.document

    async def apply_configuration(self, expected_revision: int, document: str) -> int:
        self.applied.append((expected_revision, document))
        configuration = parse_toml(document)
        self.document = document
        return configuration.revision

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


def _page(qapp: QApplication) -> tuple[DpiPage, FakeClient, ServiceModel]:
    client = FakeClient()
    model = ServiceModel()
    presenter = GuiPresenter(model, open_client=lambda: _opened(client))
    page = DpiPage(presenter, model, _sync_run)
    _sync_run(presenter.refresh)
    qapp.processEvents()
    return page, client, model


def _stage_values(page: DpiPage) -> list[tuple[int, int]]:
    return [(row.x_spin.value(), row.y_spin.value()) for row in page.rows]


def test_page_loads_stages_from_the_active_profile(qapp: QApplication) -> None:
    page, _client, _model = _page(qapp)

    profile = default_configuration().profile(default_configuration().active_profile)
    expected = [(stage.x, stage.y) for stage in profile.dpi.stages]
    assert _stage_values(page) == expected
    assert page.active_box.currentIndex() == profile.dpi.active_stage - 1
    assert not page.apply_button.isEnabled()


def test_editing_a_stage_marks_the_page_dirty(qapp: QApplication) -> None:
    page, _client, _model = _page(qapp)

    page.rows[0].x_spin.setValue(3200)

    assert page.apply_button.isEnabled()
    assert page.status_label.text() == "unsaved changes"


def test_apply_sends_a_revision_checked_document(qapp: QApplication) -> None:
    page, client, model = _page(qapp)

    page.rows[0].x_spin.setValue(3200)
    page.rows[0].y_spin.setValue(3200)
    page.apply_button.click()
    qapp.processEvents()

    expected_revision, document = client.applied[0]
    assert expected_revision == default_configuration().revision
    configuration = parse_toml(document)
    profile_id = configuration.active_profile
    assert configuration.profile(profile_id).dpi.stages[0].x == 3200
    assert configuration.revision == default_configuration().revision + 1
    assert model.apply_status == "applied"
    assert page.status_label.text() == "applied"
    assert not page.apply_button.isEnabled()


def test_add_and_remove_stage_rows(qapp: QApplication) -> None:
    page, _client, _model = _page(qapp)
    initial = len(page.rows)

    page.remove_stage(initial - 1)
    assert len(page.rows) == initial - 1

    page.add_stage()
    assert len(page.rows) == initial


def test_stage_count_is_capped_at_five(qapp: QApplication) -> None:
    page, _client, _model = _page(qapp)

    assert len(page.rows) == 5
    page.add_stage()
    assert len(page.rows) == 5
    assert not page.add_button.isEnabled()


def test_external_reload_keeps_user_edits_only_on_same_document(qapp: QApplication) -> None:
    page, client, model = _page(qapp)

    page.rows[0].x_spin.setValue(3200)
    client.document = dump_toml(default_configuration())
    model.apply_configuration(default_configuration().revision, client.document)
    qapp.processEvents()

    assert _stage_values(page)[0][0] == 3200
