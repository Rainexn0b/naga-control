import asyncio
import logging
from dataclasses import replace

import pytest
from test_configuration_authority import Store
from test_service_lifecycle_failures import FailingSession, FailingWorker, make_service
from test_service_mode import Session as ModeSession
from test_service_mode import Worker as ModeWorker
from test_service_mode import connection
from test_service_runtime import Session, Worker

from naga_control.config import dump_toml, parse_toml
from naga_control.domain.defaults import default_configuration
from naga_control.domain.errors import ConfigValidationError
from naga_control.service.configuration_authority import (
    StaleConfigurationRevisionError,
    UnknownProfileError,
)
from naga_control.service.runtime import NagaService
from naga_control.service.runtime import (
    StaleConfigurationRevisionError as RuntimeRevisionError,
)
from naga_control.service.runtime import UnknownProfileError as RuntimeProfileError


def test_error_reexports_preserve_identity() -> None:
    assert RuntimeRevisionError is StaleConfigurationRevisionError
    assert RuntimeProfileError is UnknownProfileError


async def test_invalid_document_is_parsed_before_waiting_for_service_lock() -> None:
    service = NagaService(lambda: (), lambda: None, Worker(), lambda _c, _cfg: Session())
    async with service._lock:  # pyright: ignore[reportPrivateUsage]
        with pytest.raises(ConfigValidationError):
            await asyncio.wait_for(service.apply_configuration(9, ""), timeout=1)


@pytest.mark.parametrize("operation", ["apply", "select"])
async def test_persistence_precedes_topology_rebuild_and_survives_rebuild_failure(
    operation: str,
) -> None:
    store = Store()
    calls: list[int] = []

    def discover() -> tuple[()]:
        calls.append(len(store.saved))
        if store.saved:
            raise RuntimeError("topology rebuild failed")
        return ()

    service = NagaService(discover, lambda: None, Worker(), lambda _c, _cfg: Session(), store)
    await service.start()
    try:
        with pytest.raises(RuntimeError, match="topology rebuild failed"):
            if operation == "apply":
                await service.apply_configuration(
                    0, dump_toml(replace(default_configuration(), revision=1))
                )
            else:
                await service.select_profile("default")
        assert service.configuration_revision() == 1
        assert calls == [0, 1]
        assert parse_toml(service.configuration_document()) == store.saved[0]
    finally:
        await service.stop()


async def test_persistence_failure_does_not_rebuild_topology() -> None:
    store = Store()
    discoveries: list[str] = []

    def discover() -> tuple[()]:
        discoveries.append("discover")
        return ()

    service = NagaService(discover, lambda: None, Worker(), lambda _c, _cfg: Session(), store)
    await service.start()
    store.error = OSError("cannot save")
    try:
        with pytest.raises(OSError, match="cannot save"):
            await service.apply_configuration(
                0, dump_toml(replace(default_configuration(), revision=1))
            )
        assert discoveries == ["discover"]
        assert service.configuration_revision() == 0
    finally:
        await service.stop()


async def test_cancelled_configuration_rebuild_keeps_old_session_cleanup_owned() -> None:
    events: list[str] = []
    worker = ModeWorker(events)
    old = ModeSession(events)
    old.stop_gate = asyncio.Event()
    sessions: list[ModeSession] = []

    def factory(_connection: object, _configuration: object) -> ModeSession:
        session = old if not sessions else ModeSession(events)
        sessions.append(session)
        return session

    service = NagaService(lambda: (connection(),), lambda: None, worker, factory)
    await service.start()
    change = asyncio.create_task(
        service.apply_configuration(0, dump_toml(replace(default_configuration(), revision=1)))
    )
    recovery: asyncio.Task[int] | None = None
    try:
        await asyncio.wait_for(old.stopping.wait(), 1)
        assert events[-2:] == ["stale", "session.stop"]
        change.cancel()
        with pytest.raises(asyncio.CancelledError):
            await change
        assert service.snapshot()["mode_ready"] is False
        before = list(events)
        recovery = asyncio.create_task(
            service.apply_configuration(1, dump_toml(replace(default_configuration(), revision=2)))
        )
        await asyncio.sleep(0)
        assert not recovery.done()
        assert events == before
        assert service.configuration_revision() == 1
        old.stop_gate.set()
        assert await asyncio.wait_for(recovery, 1) == 2
        assert len(sessions) == 2
        assert events.count("session.stop") == 1
    finally:
        old.stop_gate.set()
        await asyncio.gather(
            change, *([recovery] if recovery is not None else []), return_exceptions=True
        )
        await service.stop()


async def test_failed_session_barrier_prevents_recovery_but_not_final_worker_cleanup() -> None:
    events: list[str] = []
    worker = ModeWorker(events)
    failure = OSError("old session remains unsafe")

    class FailedSession(ModeSession):
        async def stop(self) -> None:
            await super().stop()
            raise failure

    session = FailedSession(events)
    service = NagaService(lambda: (connection(),), lambda: None, worker, lambda _c, _cfg: session)
    await service.start()
    try:
        with pytest.raises(OSError) as raised:
            await service.apply_configuration(
                0, dump_toml(replace(default_configuration(), revision=1))
            )
        assert raised.value is failure
        before = list(events)
        for recover in (service.rescan, service.apply_topology):
            with pytest.raises(OSError) as repeated:
                await recover((connection(),))
            assert repeated.value is failure
        assert events == before
        assert events.count("session.stop") == 1
        assert service.snapshot()["mode_ready"] is False
        with pytest.raises(OSError) as stopped:
            await service.stop()
        assert stopped.value is failure
        assert events.count("worker.stop") == 1
        before = list(events)
        await service.stop()
        assert events == before
    finally:
        await service.stop()


async def test_service_cannot_restart_after_terminal_shutdown() -> None:
    worker = Worker()
    service = NagaService(lambda: (), lambda: None, worker, lambda _c, _cfg: Session())
    await service.start()
    await service.stop()
    before = list(worker.events)
    with pytest.raises(RuntimeError, match="Naga service has been stopped"):
        await service.start()
    assert worker.events == before


@pytest.mark.parametrize("ancillary_failure", ["cancelled", "ordinary"])
async def test_shutdown_joins_ancillary_failures_without_replacing_poll_error(
    ancillary_failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = Worker()
    session = Session()
    service = NagaService(lambda: (connection(),), lambda: None, worker, lambda _c, _cfg: session)
    primary = OSError("poll failed first")

    async def poll() -> None:
        raise primary

    monkeypatch.setattr(service, "_poll_observed_state", poll)
    await service.start()
    gate = asyncio.Event()

    async def ancillary() -> None:
        await gate.wait()
        raise ValueError("ancillary cleanup failed later")

    task = asyncio.create_task(ancillary())
    service._cleanup_tasks.add(task)  # pyright: ignore[reportPrivateUsage]
    await asyncio.sleep(0)
    if ancillary_failure == "cancelled":
        task.cancel()
    else:
        gate.set()
    try:
        with pytest.raises(OSError) as raised:
            await service.stop()
        assert raised.value is primary
        assert task.done()
        assert session.events == ["start", "stop"]
        assert worker.events.count("stop") == 1
        await service.stop()
    finally:
        gate.set()
        await asyncio.gather(task, service.stop(), return_exceptions=True)


@pytest.mark.parametrize("phase", ["service_rollback", "session_rollback", "invalidate"])
async def test_new_cleanup_logs_expose_only_fixed_phase_and_exception_class(
    phase: str, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    identifiers = ("PRIVATE-SERIAL", "/sys/PRIVATE-USB", "PRIVATE-CAUSE", "PRIVATE-CONTEXT")
    primary = RuntimeError(" ".join(identifiers))
    cleanup_error = OSError(" ".join(identifiers[:2]))
    cleanup_error.__cause__ = ValueError(identifiers[2])
    cleanup_error.__context__ = RuntimeError(identifiers[3])
    events: list[str] = []
    worker, session = FailingWorker(events), FailingSession(events)
    service = make_service(worker, session)
    expected: set[str] = set()
    with caplog.at_level(logging.DEBUG):
        try:
            if phase == "service_rollback":
                worker.failure, worker.stop_error = primary, cleanup_error
                expected.add("service startup rollback cleanup failed: OSError")
            elif phase == "session_rollback":
                session.failure, session.stop_error = primary, cleanup_error
                expected.update(
                    (
                        "input forwarding startup rollback cleanup failed: OSError",
                        "detached session cleanup failed: OSError",
                        "service startup rollback cleanup failed: OSError",
                    )
                )
            else:
                await service.start()
                session.stop_error = cleanup_error

                def release_all() -> None:
                    raise ValueError(" ".join(identifiers)) from cleanup_error

                monkeypatch.setattr(session, "release_all", release_all)
                service.mark_topology_stale()
                await asyncio.gather(
                    *tuple(service._cleanup_tasks),  # pyright: ignore[reportPrivateUsage]
                    return_exceptions=True,
                )
                expected.update(
                    (
                        "unsafe session output release cleanup failed: ValueError",
                        "unsafe session stop cleanup failed: OSError",
                        "detached session cleanup failed: OSError",
                    )
                )
            if phase != "invalidate":
                with pytest.raises(RuntimeError) as raised:
                    await service.start()
                assert raised.value is primary
        finally:
            await asyncio.gather(service.stop(), return_exceptions=True)
    assert {record.getMessage() for record in caplog.records} == expected
    for record in caplog.records:
        assert record.levelno == logging.ERROR
        assert record.exc_info is record.exc_text is record.stack_info is None
        assert record.args in (("OSError",), ("ValueError",))
        for attribute in vars(record).values():
            assert not any(identifier in repr(attribute) for identifier in identifiers)
    assert not any(identifier in caplog.text for identifier in identifiers)
