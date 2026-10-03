import asyncio
from dataclasses import replace

from naga_control.config import dump_toml
from naga_control.domain.defaults import default_configuration
from naga_control.gui.models import ServiceModel
from naga_control.gui.presenter import ApplyOutcome, GuiPresenter
from naga_control.ipc.client import (
    InvalidConfigurationError,
    NagaControlClient,
    StaleRevisionError,
    UnknownProfileError,
)

SNAPSHOT = '{"status":"available","generation":2,"transport":"hyperspeed","error":null}'


class ClientScript:
    def __init__(
        self,
        *,
        apply_error: Exception | None = None,
        select_error: Exception | None = None,
        snapshot_error: Exception | None = None,
        new_revision: int = 6,
    ) -> None:
        self.apply_error = apply_error
        self.select_error = select_error
        self.snapshot_error = snapshot_error
        self.new_revision = new_revision
        self.released = False
        self.applied: tuple[int, str] | None = None
        self.selected: str | None = None
        self.document = dump_toml(default_configuration())


class FakeClient(NagaControlClient):
    def __init__(self, script: ClientScript) -> None:
        super().__init__(_NullCalls())
        self.script = script

    async def snapshot_document(self) -> str:
        if self.script.snapshot_error is not None:
            raise self.script.snapshot_error
        return SNAPSHOT

    async def release_all(self) -> None:
        self.script.released = True

    async def configuration_document(self) -> str:
        return self.script.document

    async def apply_configuration(self, expected_revision: int, document: str) -> int:
        self.script.applied = (expected_revision, document)
        if self.script.apply_error is not None:
            raise self.script.apply_error
        return self.script.new_revision

    async def select_profile(self, profile_id: str) -> int:
        if self.script.select_error is not None:
            raise self.script.select_error
        self.script.selected = profile_id
        return self.script.new_revision


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


def _presenter(
    script: ClientScript, model: ServiceModel
) -> tuple[GuiPresenter, list[NagaControlClient]]:
    clients: list[NagaControlClient] = []
    presenter = GuiPresenter(
        model,
        open_client=lambda: _opened(script, clients),
        close_client=clients.remove,
    )
    return presenter, clients


async def _opened(script: ClientScript, clients: list[NagaControlClient]) -> NagaControlClient:
    client = FakeClient(script)
    clients.append(client)
    return client


def test_refresh_populates_the_model_and_reuses_the_client() -> None:
    script = ClientScript()
    model = ServiceModel()
    presenter, clients = _presenter(script, model)

    asyncio.run(presenter.refresh())
    asyncio.run(presenter.refresh())

    assert model.connection.reachable
    assert model.snapshot is not None and model.snapshot.status == "available"
    assert model.configuration_revision == default_configuration().revision
    assert len(clients) == 1


def test_refresh_failure_drops_the_client_and_marks_unreachable() -> None:
    from dbus_next.errors import DBusError

    script = ClientScript(
        snapshot_error=DBusError("org.freedesktop.DBus.Error.ServiceUnknown", "gone")
    )
    model = ServiceModel()
    presenter, clients = _presenter(script, model)

    asyncio.run(presenter.refresh())

    assert not model.connection.reachable
    assert model.connection.detail == "gone"
    assert clients == []


def test_apply_configuration_reports_outcomes() -> None:
    model = ServiceModel()
    document = dump_toml(replace(default_configuration(), revision=1))
    cases: list[tuple[Exception | None, ApplyOutcome]] = [
        (None, ApplyOutcome.APPLIED),
        (StaleRevisionError("stale"), ApplyOutcome.STALE),
        (InvalidConfigurationError("bad"), ApplyOutcome.INVALID),
    ]
    for error, expected in cases:
        script = ClientScript(apply_error=error)
        presenter, _ = _presenter(script, model)
        outcome = asyncio.run(presenter.apply_configuration(document))
        assert outcome is expected
        if error is None:
            assert script.applied == (0, document)
            assert model.configuration_revision == 6
            assert model.configuration_document == document


def test_apply_configuration_requires_a_known_revision() -> None:
    script = ClientScript(snapshot_error=RuntimeError("no service"))
    model = ServiceModel()
    presenter, _ = _presenter(script, model)

    assert asyncio.run(presenter.apply_configuration("doc")) is ApplyOutcome.UNREACHABLE
    assert not model.connection.reachable


def test_select_profile_reports_invalid_and_applied() -> None:
    for error, expected in [
        (UnknownProfileError("nope"), ApplyOutcome.INVALID),
        (None, ApplyOutcome.APPLIED),
    ]:
        script = ClientScript(select_error=error)
        model = ServiceModel()
        presenter, _ = _presenter(script, model)

        assert asyncio.run(presenter.select_profile("fps")) is expected

    assert script.selected == "fps"


def test_release_all_refreshes_after_release() -> None:
    script = ClientScript()
    model = ServiceModel()
    presenter, _ = _presenter(script, model)

    asyncio.run(presenter.release_all())

    assert script.released
    assert model.connection.reachable


def test_queued_apply_retains_its_base_revision_after_model_refresh() -> None:
    script = ClientScript(apply_error=StaleRevisionError("stale"))
    model = ServiceModel()
    presenter, _clients = _presenter(script, model)
    document = dump_toml(replace(default_configuration(), revision=1))
    newer = dump_toml(replace(default_configuration(), revision=9))
    model.apply_configuration(9, newer)

    assert asyncio.run(presenter.apply_configuration(document)) is ApplyOutcome.STALE
    assert script.applied == (0, document)
