import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable
from dataclasses import replace

import pytest
from test_service_mode import Session, Worker
from test_service_runtime import Store
from test_session_ownership import connection
from test_session_teardown import CLEANUP, make_session

from naga_control.adapters.evdev.discovery import NagaConnection
from naga_control.application.remapping import FirstSliceSession
from naga_control.config import dump_toml, parse_toml
from naga_control.domain.defaults import default_configuration
from naga_control.domain.profiles import Configuration
from naga_control.service.runtime import NagaService


async def bounded[T](operation: Awaitable[T]) -> T:
    return await asyncio.wait_for(operation, 2)


class BarrierSession(Session):
    def __init__(self, events: list[str]) -> None:
        super().__init__(events)
        self.error: OSError | None = None
        self.completed = asyncio.Event()

    async def stop(self) -> None:
        await super().stop()
        self.events.append("session.stopped")
        self.completed.set()
        if self.error is not None:
            raise self.error


class Scenario:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.worker, self.store = Worker(self.events), Store()
        self.sessions: list[BarrierSession] = []
        configuration = default_configuration()
        self.configuration = replace(
            configuration,
            profiles=(
                *configuration.profiles,
                ("other", replace(configuration.profile("default"), display_name="Other")),
            ),
        )
        self.service = NagaService(
            lambda: (connection(),),
            lambda: self.configuration,
            self.worker,
            self.factory,
            self.store,
        )

    def factory(self, _: NagaConnection, configuration: Configuration) -> BarrierSession:
        session = BarrierSession(self.events)
        self.sessions.append(session)
        return session

    def command(self, name: str) -> Awaitable[object]:
        service = self.service
        if name == "apply_configuration":
            revision = service.configuration_revision()
            configuration = replace(
                parse_toml(service.configuration_document()), revision=revision + 1, mode="firmware"
            )
            return service.apply_configuration(revision, dump_toml(configuration))
        if name == "select_profile":
            return service.select_profile("other")
        if name == "begin_calibration":
            return service.begin_calibration()
        return service.end_calibration()


@pytest.fixture
async def scenario() -> AsyncIterator[Scenario]:
    baseline = asyncio.all_tasks()
    case = Scenario()
    try:
        await bounded(case.service.start())
        yield case
    finally:
        for session in case.sessions:
            if session.stop_gate is not None:
                session.stop_gate.set()
        await bounded(asyncio.gather(case.service.stop(), return_exceptions=True))
        await asyncio.sleep(0)
        assert not (asyncio.all_tasks() - baseline - {asyncio.current_task()})


@pytest.mark.integration
@pytest.mark.parametrize("rebuild", ["topology", "configuration"])
async def test_real_session_rollback_failure_remains_a_service_barrier(rebuild: str) -> None:
    baseline = asyncio.all_tasks()
    events: list[str] = []
    worker, store = Worker(events), Store()
    primary, cleanup_error = (
        RuntimeError("reader activation failed"),
        OSError("output close failed"),
    )
    first, _, _, _, _ = make_session(events)
    failed, readers, keyboard, mouse, actions = make_session(events, primary)
    keyboard.errors["close"] = cleanup_error
    sessions: list[FirstSliceSession] = []

    def factory(_: NagaConnection, configuration: Configuration) -> FirstSliceSession:
        session = first if not sessions else failed
        sessions.append(session)
        return session

    service = NagaService(lambda: (connection(),), default_configuration, worker, factory, store)
    try:
        await bounded(service.start())
        assert service.snapshot()["mode_ready"] is True
        assert first.running
        events.clear()
        updated = replace(default_configuration(), revision=1)
        with pytest.raises(RuntimeError) as raised:
            await bounded(
                service.apply_topology((connection(),))
                if rebuild == "topology"
                else service.apply_configuration(0, dump_toml(updated))
            )
        assert raised.value is primary
        assert all(reader.stopped for reader in readers)
        assert keyboard.closed and mouse.closed and not failed.running
        assert actions.stopping.is_set()
        assert sessions == [first, failed]
        assert service.snapshot()["mode_ready"] is False
        if rebuild == "configuration":
            assert store.saved == [updated]
            assert parse_toml(service.configuration_document()) == updated
        before = list(events)
        for request in (service.apply_topology, service.rescan):
            for _ in range(2):
                with pytest.raises(OSError) as rejected:
                    await bounded(request((connection(),)))
                assert rejected.value is cleanup_error
                assert events == before
                assert sessions == [first, failed]
                assert service.snapshot()["mode_ready"] is False
        # Re-await internal startup rollback, rather than destroying outputs again.
        with pytest.raises(OSError) as cached:
            await bounded(failed.stop())
        assert cached.value is cleanup_error
        assert events == before
        with pytest.raises(OSError) as stopped:
            await bounded(service.stop())
        assert stopped.value is cleanup_error
        assert events == [*before, "worker.stop"]
    finally:
        await bounded(
            asyncio.gather(service.stop(), first.stop(), failed.stop(), return_exceptions=True)
        )
        assert not (asyncio.all_tasks() - baseline)


COMMANDS = ["apply_configuration", "select_profile", "begin_calibration", "end_calibration"]


@pytest.mark.parametrize("command", COMMANDS)
async def test_known_failed_barrier_rejects_before_persistence_or_flags(
    scenario: Scenario, command: str
) -> None:
    case, service = scenario, scenario.service
    if command == "end_calibration":
        await bounded(service.begin_calibration())
    session = case.sessions[-1]
    error = session.error = OSError("session cleanup failed")
    with pytest.raises(OSError) as initial:
        await bounded(service.apply_topology((connection(),)))
    assert initial.value is error
    before = list(case.events)
    document, revision = service.configuration_document(), service.configuration_revision()
    saved, calibrating = list(case.store.saved), service.snapshot()["calibrating"]
    for _ in range(2):
        with pytest.raises(OSError) as rejected:
            await bounded(case.command(command))
        assert rejected.value is error
        assert case.events == before
        assert service.configuration_document() == document
        assert service.configuration_revision() == revision
        assert case.store.saved == saved
        assert service.snapshot()["calibrating"] == calibrating
        assert service.snapshot()["mode_ready"] is False
    with pytest.raises(OSError):
        await bounded(service.stop())
    assert case.events == [*before, "worker.stop"]


@pytest.mark.parametrize("command", COMMANDS)
async def test_terminal_stop_rejects_mutating_commands_before_persistence_or_flags(
    scenario: Scenario, command: str
) -> None:
    case, service = scenario, scenario.service
    if command == "end_calibration":
        await bounded(service.begin_calibration())
    await bounded(service.stop())
    document, revision = service.configuration_document(), service.configuration_revision()
    saved, calibrating = list(case.store.saved), service.snapshot()["calibrating"]
    before = list(case.events)
    with pytest.raises(RuntimeError):
        await bounded(case.command(command))
    assert service.configuration_document() == document
    assert service.configuration_revision() == revision
    assert case.store.saved == saved
    assert service.snapshot()["calibrating"] == calibrating
    assert case.events == before


async def test_accepted_configuration_remains_saved_when_its_rebuild_fails(
    scenario: Scenario,
) -> None:
    case, service = scenario, scenario.service
    error = case.sessions[0].error = OSError("cleanup after accepted update failed")
    updated = replace(case.configuration, revision=1, active_profile="other")
    with pytest.raises(OSError) as raised:
        await bounded(service.apply_configuration(0, dump_toml(updated)))
    assert raised.value is error
    assert case.store.saved == [updated]
    assert service.configuration_revision() == 1
    assert parse_toml(service.configuration_document()) == updated
    assert len(case.sessions) == 1
    assert case.events[-3:] == ["stale", "session.stop", "session.stopped"]
    assert service.snapshot()["mode_ready"] is False


async def test_cancelled_last_transition_waiter_logs_late_failure_and_keeps_barrier(
    scenario: Scenario, caplog: pytest.LogCaptureFixture
) -> None:
    case, service = scenario, scenario.service
    session = case.sessions[0]
    session.stop_gate = asyncio.Event()
    error = session.error = OSError("late cleanup failure")
    transition = asyncio.create_task(service.apply_topology((connection(),)))
    try:
        await bounded(session.stopping.wait())
        assert case.events[-2:] == ["stale", "session.stop"]
        assert case.events.count("stale") == 1  # Fake-worker fencing trace, not queue proof.
        transition.cancel()
        with pytest.raises(asyncio.CancelledError):
            await bounded(transition)
        assert not session.completed.is_set()
        before = list(case.events)
        caplog.clear()
        with caplog.at_level(logging.ERROR):
            session.stop_gate.set()
            await bounded(session.completed.wait())
            await asyncio.sleep(0)  # Let the owner's completion diagnostic run, with no waiter.
        assert case.events == [*before, "session.stopped"]
        assert any(
            record.levelno >= logging.ERROR
            and "session" in record.getMessage().splitlines()[0].lower()
            and any(
                phase in record.getMessage().splitlines()[0].lower()
                for phase in ("cleanup", "stop")
            )
            and (
                "OSError" in record.getMessage()
                or (record.exc_info is not None and record.exc_info[1] is error)
            )
            for record in caplog.records
        )
        before = list(case.events)
        for request in (service.apply_topology, service.rescan):
            with pytest.raises(OSError) as rejected:
                await bounded(request((connection(),)))
            assert rejected.value is error
        assert case.events == before and len(case.sessions) == 1
        assert service.snapshot()["mode_ready"] is False
        with pytest.raises(OSError):
            await bounded(service.stop())
        assert case.events == [*before, "worker.stop"]
        await bounded(asyncio.gather(service.stop(), return_exceptions=True))
        assert case.events.count("worker.stop") == 1
    finally:
        session.stop_gate.set()
        await bounded(asyncio.gather(transition, return_exceptions=True))


async def test_concurrent_real_session_stoppers_share_cached_first_cleanup_error() -> None:
    baseline = asyncio.all_tasks()
    events: list[str] = []
    session, _, keyboard, _, actions = make_session(events)
    first_error = keyboard.errors["close"] = OSError("first cleanup failure")
    actions.error, actions.block = ValueError("later cleanup failure"), True
    waiters: list[asyncio.Task[None]] = []
    try:
        await bounded(session.start())
        waiters.append(asyncio.create_task(session.stop()))
        await bounded(actions.stopping.wait())
        waiters.append(asyncio.create_task(session.stop()))
        await asyncio.sleep(0)
        assert all(not waiter.done() for waiter in waiters)
        assert all(events.count(name) == 1 for name in CLEANUP)
        actions.release.set()
        results = await bounded(asyncio.gather(*waiters, return_exceptions=True))
        assert all(result is first_error for result in results)
        before = list(events)
        for _ in range(2):
            with pytest.raises(OSError) as cached:
                await bounded(session.stop())
            assert cached.value is first_error
            assert events == before
    finally:
        actions.release.set()
        await bounded(asyncio.gather(*waiters, session.stop(), return_exceptions=True))
        assert not session.running
        assert not (asyncio.all_tasks() - baseline)
