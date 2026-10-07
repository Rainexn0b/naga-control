"""Fake-only startup, cancellation, and independent CLI teardown contracts."""

import asyncio
from collections.abc import Callable
from typing import Literal

import pytest
from dbus_next.constants import NameFlag, RequestNameReply
from test_service_cli import RunningStopEvent, Service

from naga_control.domain.hardware import HardwareState
from naga_control.ipc.service import NagaControlInterface
from naga_control.service import service_cli

PHASES = ("bus-connect", "export", "name", "service-start", "lifecycle-start")
CLEANUP = ("watcher-stop", "lifecycle-stop", "service-stop", "disconnect")


class Boundary(Service):
    def __init__(self) -> None:
        super().__init__()
        self.errors: dict[str, Exception] = {}
        self.blocked: str | None = None
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.stopped = RunningStopEvent()
        self.interruption: asyncio.CancelledError | None = None
        self.watcher_joined = False

    def record(self, phase: str) -> None:
        self.events.append(phase)
        if phase in self.errors:
            raise self.errors[phase]

    async def step(self, phase: str) -> None:
        self.record(phase)
        if self.blocked == phase:
            self.entered.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError as exc:
                self.interruption = exc
                raise

    async def start(self) -> HardwareState:
        await self.step("service-start")
        return HardwareState("absent", 1)

    async def stop(self) -> None:
        self.record("service-stop")

    async def connect(self) -> "Boundary":
        await self.step("bus-connect")
        return self

    def export(self, path: str, interface: NagaControlInterface) -> None:
        self.record("export")

    async def request_name(self, name: str, flags: NameFlag = NameFlag.NONE) -> object:
        await self.step("name")
        return RequestNameReply.PRIMARY_OWNER

    def disconnect(self) -> None:
        self.record("disconnect")

    async def watcher(self) -> None:
        self.events.append("watcher-start")
        self.entered.set()
        try:
            await self.release.wait()
        finally:
            self.watcher_joined = True
            self.record("watcher-stop")

    async def run(self, *, watcher: bool = False) -> None:
        await service_cli.run(
            self,
            install_signal_handler=lambda handled, callback: None,
            stop_event=self.stopped,
            bus_factory=self.connect,
            topology_watcher=self.watcher if watcher else None,
            openrazer_lifecycle=Lifecycle(self),
        )


class Lifecycle:
    def __init__(self, boundary: Boundary) -> None:
        self.boundary = boundary

    async def start(self) -> None:
        await self.boundary.step("lifecycle-start")

    async def stop(self) -> None:
        self.boundary.record("lifecycle-stop")


def expected_cleanup(phase: str) -> list[str]:
    return (
        (["lifecycle-stop"] if phase in ("lifecycle-start", "wait") else [])
        + (["service-stop"] if phase in ("service-start", "lifecycle-start", "wait") else [])
        + ([] if phase == "bus-connect" else ["disconnect"])
    )


@pytest.mark.parametrize("phase", PHASES)
async def test_startup_failure_cleans_only_acquired_resources_and_preserves_error(
    phase: str,
) -> None:
    boundary = Boundary()
    original = OSError(f"fake {phase} failure")
    boundary.errors[phase] = original
    with pytest.raises(OSError) as raised:
        await boundary.run(watcher=True)
    assert raised.value is original
    assert boundary.events == list(PHASES[: PHASES.index(phase) + 1]) + expected_cleanup(phase)
    assert "watcher-start" not in boundary.events
    if phase in ("bus-connect", "export", "name"):
        assert "service-start" not in boundary.events and "lifecycle-start" not in boundary.events


@pytest.mark.parametrize("phase", ["bus-connect", "name", "service-start", "lifecycle-start"])
@pytest.mark.parametrize("cleanup_error", [False, True])
async def test_in_flight_startup_cancellation_keeps_identity_and_attempts_cleanup(
    phase: str, cleanup_error: bool
) -> None:
    boundary = Boundary()
    boundary.blocked = phase
    if cleanup_error:
        boundary.errors.update({item: RuntimeError(item) for item in CLEANUP[1:]})
    task = asyncio.create_task(boundary.run(watcher=True))
    try:
        await asyncio.wait_for(boundary.entered.wait(), timeout=2)
        task.cancel("single fake startup cancellation")
        try:
            async with asyncio.timeout(2):
                await task
        except BaseException as observed:
            assert boundary.events == list(PHASES[: PHASES.index(phase) + 1]) + expected_cleanup(
                phase
            )
            assert isinstance(observed, asyncio.CancelledError)
            assert observed is boundary.interruption
            assert observed.args == ("single fake startup cancellation",)
        else:
            pytest.fail("startup cancellation must propagate")
        assert "watcher-start" not in boundary.events
    finally:
        if not task.done():
            task.cancel()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=2)


@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize("cleanup_phase", CLEANUP[1:])
async def test_primary_startup_error_survives_ordinary_cleanup_failure(
    phase: str, cleanup_phase: str
) -> None:
    boundary = Boundary()
    primary = LookupError(f"primary {phase}")
    boundary.errors[phase] = primary
    boundary.errors[cleanup_phase] = RuntimeError(f"secondary {cleanup_phase}")
    try:
        await boundary.run()
    except Exception as observed:
        assert boundary.events == list(PHASES[: PHASES.index(phase) + 1]) + expected_cleanup(phase)
        assert observed is primary
    else:
        pytest.fail("primary startup error must propagate")


@pytest.mark.parametrize("cleanup_phase", [None, *CLEANUP])
@pytest.mark.parametrize("cancelled", [False, True])
async def test_running_cleanup_is_independent_and_preserves_single_cancellation(
    cleanup_phase: str | None, cancelled: bool
) -> None:
    boundary = Boundary()
    secondary = RuntimeError(f"fake {cleanup_phase} failure")
    if cleanup_phase is not None:
        boundary.errors[cleanup_phase] = secondary
    cancellations: list[asyncio.CancelledError] = []

    class StopEvent(RunningStopEvent):
        async def wait(self) -> Literal[True]:
            try:
                return await super().wait()
            except asyncio.CancelledError as exc:
                cancellations.append(exc)
                raise

    boundary.stopped = StopEvent()
    task = asyncio.create_task(boundary.run(watcher=True))
    try:
        await asyncio.wait_for(boundary.entered.wait(), timeout=2)
        if cancelled:
            task.cancel("single fake running cancellation")
        else:
            boundary.stopped.set()
        try:
            async with asyncio.timeout(2):
                await task
        except BaseException as observed:
            assert boundary.events[-4:] == list(CLEANUP)
            assert boundary.watcher_joined
            if cancelled:
                assert isinstance(observed, asyncio.CancelledError)
                assert cancellations == [observed]
                assert observed.args == ("single fake running cancellation",)
            else:
                assert observed is secondary
        else:
            assert cleanup_phase is None and not cancelled
        assert boundary.events[-4:] == list(CLEANUP)
        assert boundary.watcher_joined
    finally:
        if not task.done():
            task.cancel()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=2)


@pytest.mark.parametrize("watcher", [False, True])
async def test_first_standalone_cleanup_failure_is_observable_after_all_attempts(
    watcher: bool,
) -> None:
    boundary = Boundary()
    cleanup = list(CLEANUP if watcher else CLEANUP[1:])
    failures = {item: RuntimeError(item) for item in cleanup}
    boundary.errors.update(failures)
    task = asyncio.create_task(boundary.run(watcher=watcher))
    try:
        await asyncio.wait_for(boundary.stopped.wait_entered.wait(), timeout=2)
        if watcher:
            await asyncio.wait_for(boundary.entered.wait(), timeout=2)
        boundary.stopped.set()
        with pytest.raises(RuntimeError) as raised:
            async with asyncio.timeout(2):
                await task
        assert boundary.events[-len(cleanup) :] == cleanup
        assert raised.value is failures[cleanup[0]]
    finally:
        if not task.done():
            task.cancel()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=2)


@pytest.mark.parametrize("cleanup_phase", CLEANUP)
async def test_running_body_error_survives_ordinary_cleanup_failure(cleanup_phase: str) -> None:
    boundary = Boundary()
    primary = LookupError("fake running body failure")
    boundary.errors[cleanup_phase] = RuntimeError("secondary cleanup failure")
    fail_body = asyncio.Event()

    class StopEvent(RunningStopEvent):
        async def wait(self) -> Literal[True]:
            self.wait_entered.set()
            await fail_body.wait()
            raise primary

    boundary.stopped = StopEvent()
    task = asyncio.create_task(boundary.run(watcher=True))
    try:
        await asyncio.wait_for(boundary.entered.wait(), timeout=2)
        fail_body.set()
        try:
            async with asyncio.timeout(2):
                await task
        except Exception as observed:
            assert boundary.events[-4:] == list(CLEANUP)
            assert observed is primary
        else:
            pytest.fail("running body error must propagate")
    finally:
        if not task.done():
            task.cancel()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=2)


async def test_successful_shutdown_joins_watcher_before_stopping_owned_resources() -> None:
    boundary = Boundary()
    task = asyncio.create_task(boundary.run(watcher=True))
    try:
        await asyncio.wait_for(boundary.entered.wait(), timeout=2)
        boundary.stopped.set()
        async with asyncio.timeout(2):
            await task
        assert boundary.events[-4:] == list(CLEANUP)
        assert boundary.watcher_joined
    finally:
        if not task.done():
            task.cancel()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=2)


async def test_duplicate_bus_owner_aborts_before_watcher_and_disconnects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = Boundary()

    async def duplicate(name: str, flags: NameFlag = NameFlag.NONE) -> object:
        assert flags == NameFlag.DO_NOT_QUEUE
        boundary.record("name")
        return RequestNameReply.EXISTS

    monkeypatch.setattr(boundary, "request_name", duplicate)
    boundary.stopped.set()
    with pytest.raises(RuntimeError):
        await boundary.run(watcher=True)
    assert "watcher-start" not in boundary.events
    assert boundary.events == ["bus-connect", "export", "name", "disconnect"]


async def test_signal_callbacks_are_injected_without_registering_real_signals() -> None:
    boundary = Boundary()
    callbacks: list[Callable[[], None]] = []
    boundary.stopped.set()
    await service_cli.run(
        boundary,
        install_signal_handler=lambda handled, callback: callbacks.append(callback),
        stop_event=boundary.stopped,
        bus_factory=boundary.connect,
    )
    assert len(callbacks) == 2
    for callback in callbacks:
        callback()
    assert boundary.events == ["bus-connect", "export", "name", "disconnect"]
