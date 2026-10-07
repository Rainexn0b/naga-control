"""Direct failure-branch characterization for GuiPresenter (DEBT-12)."""

import asyncio
import os
from collections.abc import Callable, Coroutine, Iterator
from dataclasses import replace
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from naga_control.config import dump_toml, parse_toml
from naga_control.domain.defaults import default_configuration
from naga_control.gui.models import ServiceModel
from naga_control.gui.overview_page import OverviewPage
from naga_control.gui.presenter import ApplyOutcome, GuiPresenter
from naga_control.ipc.client import (
    InvalidConfigurationError,
    NagaControlClient,
    StaleRevisionError,
    UnknownProfileError,
)

SNAPSHOT_HEALTHY = '{"status":"available","generation":2,"transport":"hyperspeed","error":null}'
SNAPSHOT_RECOVERED = '{"status":"available","generation":9,"transport":"wired","error":null}'


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


class FailingClient(NagaControlClient):
    """Healthy snapshot/config reads with per-operation failure injection."""

    def __init__(self, document: str, snapshot: str) -> None:
        super().__init__(_NullCalls())
        self.document = document
        self.snapshot = snapshot
        self.fail_release: Exception | None = None
        self.fail_begin: Exception | None = None
        self.fail_end: Exception | None = None
        self.fail_select: Exception | None = None
        self.fail_apply: Exception | None = None
        self.fail_snapshot: Exception | None = None
        self.snapshot_calls = 0
        self.config_calls = 0
        self.release_calls = 0
        self.begin_calls = 0
        self.end_calls = 0
        self.select_calls = 0
        self.apply_calls = 0
        self.released = False
        self.began = False
        self.ended = False
        self.selected: str | None = None
        self.applied: tuple[int, str] | None = None

    async def snapshot_document(self) -> str:
        self.snapshot_calls += 1
        if self.fail_snapshot is not None:
            raise self.fail_snapshot
        return self.snapshot

    async def configuration_document(self) -> str:
        self.config_calls += 1
        return self.document

    async def release_all(self) -> None:
        self.release_calls += 1
        if self.fail_release is not None:
            raise self.fail_release
        self.released = True

    async def begin_calibration(self) -> bool:
        self.begin_calls += 1
        if self.fail_begin is not None:
            raise self.fail_begin
        self.began = True
        return True

    async def end_calibration(self) -> bool:
        self.end_calls += 1
        if self.fail_end is not None:
            raise self.fail_end
        self.ended = True
        return True

    async def select_profile(self, profile_id: str) -> int:
        self.select_calls += 1
        if self.fail_select is not None:
            raise self.fail_select
        self.selected = profile_id
        return parse_toml(self.document).revision

    async def apply_configuration(self, expected_revision: int, document: str) -> int:
        self.apply_calls += 1
        if self.fail_apply is not None:
            raise self.fail_apply
        self.applied = (expected_revision, document)
        return parse_toml(document).revision


class Provider:
    """Single-current-client opener with close tracking."""

    def __init__(self, current: FailingClient) -> None:
        self.current = current
        self.opens: list[FailingClient] = []
        self.closes: list[FailingClient] = []
        self.close_error: Exception | None = None

    async def open(self) -> NagaControlClient:
        self.opens.append(self.current)
        return self.current

    def close(self, client: NagaControlClient) -> None:
        self.closes.append(cast(FailingClient, client))
        if self.close_error is not None:
            raise self.close_error


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    yield cast(QApplication, app)


def _setup() -> tuple[ServiceModel, Provider, FailingClient, GuiPresenter, list[int]]:
    client = FailingClient(dump_toml(default_configuration()), SNAPSHOT_HEALTHY)
    provider = Provider(client)
    model = ServiceModel()
    presenter = GuiPresenter(model, open_client=provider.open, close_client=provider.close)
    notifications: list[int] = []
    model.add_listener(lambda: notifications.append(1))
    return model, provider, client, presenter, notifications


def _connect(model: ServiceModel, presenter: GuiPresenter, provider: Provider) -> None:
    asyncio.run(presenter.refresh())
    assert model.connection.reachable
    assert len(provider.opens) == 1


def _run(factory: Callable[[], Coroutine[Any, Any, object]]) -> None:
    asyncio.run(factory())


def test_refresh_control_failure_drops_client() -> None:
    model, provider, client, presenter, notifications = _setup()
    _connect(model, presenter, provider)
    revision = model.configuration_revision
    before_notify = len(notifications)
    client.fail_snapshot = RuntimeError("snapshot gone")

    asyncio.run(presenter.refresh())

    assert not model.connection.reachable
    assert model.connection.detail == "snapshot gone"
    assert provider.closes == [client]
    assert model.configuration_revision == revision
    assert len(notifications) > before_notify


def test_release_all_failure_marks_unreachable_without_refresh() -> None:
    model, provider, client, presenter, notifications = _setup()
    _connect(model, presenter, provider)
    snapshots = client.snapshot_calls
    configs = client.config_calls
    before_notify = len(notifications)
    client.fail_release = RuntimeError("release boom")

    asyncio.run(presenter.release_all())

    assert not client.released
    assert client.release_calls == 1
    assert client.snapshot_calls == snapshots
    assert client.config_calls == configs
    assert provider.closes == [client]
    assert not model.connection.reachable
    assert model.connection.detail == "release boom"
    assert len(notifications) > before_notify


def test_begin_calibration_failure_marks_unreachable_without_refresh() -> None:
    model, provider, client, presenter, _ = _setup()
    _connect(model, presenter, provider)
    snapshots = client.snapshot_calls
    client.fail_begin = RuntimeError("begin boom")

    asyncio.run(presenter.begin_calibration())

    assert not client.began
    assert client.begin_calls == 1
    assert client.snapshot_calls == snapshots
    assert provider.closes == [client]
    assert not model.connection.reachable
    assert model.connection.detail == "begin boom"


def test_end_calibration_empty_message_uses_exception_type() -> None:
    model, provider, client, presenter, _ = _setup()
    _connect(model, presenter, provider)
    snapshots = client.snapshot_calls
    client.fail_end = RuntimeError()

    asyncio.run(presenter.end_calibration())

    assert not client.ended
    assert client.end_calls == 1
    assert client.snapshot_calls == snapshots
    assert provider.closes == [client]
    assert not model.connection.reachable
    assert model.connection.detail == "RuntimeError"


def test_select_profile_generic_failure_returns_unreachable() -> None:
    model, provider, client, presenter, _ = _setup()
    _connect(model, presenter, provider)
    snapshots = client.snapshot_calls
    client.fail_select = RuntimeError("select boom")

    outcome = asyncio.run(presenter.select_profile("fps"))

    assert outcome is ApplyOutcome.UNREACHABLE
    assert client.selected is None
    assert client.select_calls == 1
    assert client.snapshot_calls == snapshots
    assert provider.closes == [client]
    assert not model.connection.reachable
    assert model.connection.detail == "select boom"


def test_apply_configuration_generic_failure_returns_unreachable() -> None:
    model, provider, client, presenter, _ = _setup()
    _connect(model, presenter, provider)
    snapshots = client.snapshot_calls
    revision = model.configuration_revision
    document = dump_toml(replace(default_configuration(), revision=1))
    client.fail_apply = RuntimeError("apply boom")

    outcome = asyncio.run(presenter.apply_configuration(document))

    assert outcome is ApplyOutcome.UNREACHABLE
    assert client.applied is None
    assert client.apply_calls == 1
    assert client.snapshot_calls == snapshots
    assert provider.closes == [client]
    assert not model.connection.reachable
    assert model.connection.detail == "apply boom"
    assert model.configuration_revision == revision


def test_failed_operation_recovers_with_new_client() -> None:
    model, provider, client, presenter, notifications = _setup()
    _connect(model, presenter, provider)
    client.fail_release = RuntimeError("release boom")
    asyncio.run(presenter.release_all())
    assert not model.connection.reachable
    old_snapshots = client.snapshot_calls
    before_notify = len(notifications)
    recovered_document = dump_toml(replace(default_configuration(), revision=7))
    recovered = FailingClient(recovered_document, SNAPSHOT_RECOVERED)
    provider.current = recovered
    asyncio.run(presenter.refresh())

    assert model.connection.reachable
    assert model.snapshot is not None and model.snapshot.generation == 9
    assert model.configuration_revision == 7
    assert model.configuration_document == recovered_document
    assert len(provider.opens) == 2
    assert provider.opens[1] is recovered
    assert client.snapshot_calls == old_snapshots
    assert len(notifications) > before_notify


def test_close_error_still_marks_unreachable_and_recovers() -> None:
    model, provider, client, presenter, _ = _setup()
    _connect(model, presenter, provider)
    provider.close_error = RuntimeError("close boom")
    client.fail_release = RuntimeError("release boom")

    asyncio.run(presenter.release_all())

    assert provider.closes == [client]
    assert not model.connection.reachable
    assert model.connection.detail == "release boom"
    provider.close_error = None
    recovered = FailingClient(dump_toml(default_configuration()), SNAPSHOT_RECOVERED)
    provider.current = recovered
    asyncio.run(presenter.refresh())

    assert model.connection.reachable
    assert len(provider.opens) == 2
    assert provider.opens[1] is recovered


def test_failure_reaches_visible_overview_label(qapp: QApplication) -> None:
    model, provider, client, presenter, _ = _setup()
    _connect(model, presenter, provider)
    page = OverviewPage(presenter, model, _run)
    assert page.connection_label.text() == "online"

    client.fail_release = RuntimeError("release boom")
    asyncio.run(presenter.release_all())
    qapp.processEvents()

    assert not model.connection.reachable
    assert page.connection_label.text() == "offline: release boom"
    page.close()


def test_typed_errors_are_not_blanket_unreachable() -> None:
    model, provider, client, presenter, _ = _setup()
    _connect(model, presenter, provider)

    client.fail_select = UnknownProfileError("nope")
    assert asyncio.run(presenter.select_profile("missing")) is ApplyOutcome.INVALID
    assert model.connection.reachable
    document = dump_toml(replace(default_configuration(), revision=1))
    client.fail_apply = StaleRevisionError("stale")
    assert asyncio.run(presenter.apply_configuration(document)) is ApplyOutcome.STALE
    assert model.connection.reachable

    client.fail_apply = InvalidConfigurationError("bad")
    assert asyncio.run(presenter.apply_configuration(document)) is ApplyOutcome.INVALID
    assert model.connection.reachable
    assert provider.closes == []
