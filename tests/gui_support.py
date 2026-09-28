"""Shared fakes for offscreen GUI page tests."""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from naga_control.config import parse_toml
from naga_control.gui.models import ServiceModel
from naga_control.gui.presenter import GuiPresenter
from naga_control.ipc.client import NagaControlClient

SNAPSHOT = '{"status":"available","generation":9,"transport":"hyperspeed","error":null}'


class NullCalls:
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
    """Records applies and serves a mutable configuration document."""

    def __init__(self, document: str) -> None:
        super().__init__(NullCalls())
        self.document = document
        self.applied: list[tuple[int, str]] = []

    async def snapshot_document(self) -> str:
        return SNAPSHOT

    async def release_all(self) -> None:
        return None

    async def configuration_document(self) -> str:
        return self.document

    async def apply_configuration(self, expected_revision: int, document: str) -> int:
        self.applied.append((expected_revision, document))
        self.document = document
        return parse_toml(document).revision

    async def select_profile(self, profile_id: str) -> int:
        return 1


async def opened(client: NagaControlClient) -> NagaControlClient:
    return client


def sync_run(factory: Callable[[], Coroutine[Any, Any, object]]) -> None:
    asyncio.run(factory())


def make_presenter(document: str) -> tuple[GuiPresenter, ServiceModel, FakeClient]:
    from naga_control.config import dump_toml
    from naga_control.domain.defaults import default_configuration

    client = FakeClient(document or dump_toml(default_configuration()))
    model = ServiceModel()
    presenter = GuiPresenter(model, open_client=lambda: opened(client))
    return presenter, model, client
