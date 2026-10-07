"""Caller cancellation must join CLI cleanup without stranding its public name."""

import asyncio
from collections.abc import Awaitable
from typing import Literal

import pytest
from service_reservation_fakes import (
    SECRET,
    Auxiliary,
    Boundary,
    exported_call,
    running,
    unavailable,
)
from test_service_cli import RunningStopEvent
from test_service_mode import Session, Worker, connection

from naga_control.domain.defaults import default_configuration
from naga_control.service.runtime import NagaService
from naga_control.service.service_cli import run


@pytest.fixture
def delivered_cancellations(monkeypatch: pytest.MonkeyPatch) -> list[asyncio.CancelledError]:
    cancellations: list[asyncio.CancelledError] = []
    shield = asyncio.shield

    async def observe_shield[T](awaitable: Awaitable[T]) -> T:
        # Retain real shielding; only observe the exact exceptions delivered to its caller.
        try:
            return await shield(awaitable)
        except asyncio.CancelledError as exc:
            cancellations.append(exc)
            raise

    monkeypatch.setattr(asyncio, "shield", observe_shield)
    return cancellations


class BodyStopEvent(RunningStopEvent):
    def __init__(self) -> None:
        super().__init__()
        self.error: RuntimeError | None = None
        self.interruption: asyncio.CancelledError | None = None

    async def wait(self) -> Literal[True]:
        try:
            result = await super().wait()
            if self.error is not None:
                raise self.error
            return result
        except asyncio.CancelledError as exc:
            self.interruption = exc
            raise


class CleanupAuxiliary(Auxiliary):
    async def stop(self) -> None:
        try:
            await self.boundary.step("aux-stop")
        finally:
            self.boundary.events.append("aux-finished")


class CleanupBoundary(Boundary):
    def __init__(self) -> None:
        super().__init__()
        self.entered["aux-stop"] = asyncio.Event()
        self.release["aux-stop"] = asyncio.Event()

    async def run(self) -> None:
        await run(
            self,
            install_signal_handler=lambda handled, callback: None,
            stop_event=self.stopped,
            bus_factory=self.connect,
            topology_watcher=self.watcher,
            openrazer_lifecycle=CleanupAuxiliary(self),
        )


async def assert_reserved_and_unavailable(boundary: Boundary) -> None:
    assert boundary.bus.shared.owner is boundary.bus
    assert "disconnect" not in boundary.events
    assert boundary.bus.interface is not None
    await unavailable(asyncio.create_task(exported_call(boundary.bus.interface)))
    duplicate = Boundary(boundary.bus.shared)
    async with running(duplicate) as task:
        with pytest.raises(RuntimeError):
            await task
    assert duplicate.events == ["connect", "export", "name", "disconnect"]
    assert duplicate.calls == []
    assert boundary.bus.shared.owner is boundary.bus


@pytest.mark.parametrize("phase", ["aux-stop", "stop"])
@pytest.mark.parametrize("body", ["normal", "error", "cancel"])
@pytest.mark.parametrize("cancel_count", [1, 3])
@pytest.mark.parametrize("secondary_error", [False, True])
async def test_cleanup_is_joined_despite_caller_cancellation_and_preserves_primary(
    phase: str,
    body: str,
    cancel_count: int,
    secondary_error: bool,
    delivered_cancellations: list[asyncio.CancelledError],
) -> None:
    boundary = CleanupBoundary()
    stopped = BodyStopEvent()
    boundary.stopped = stopped
    boundary.blocked.add(phase)
    primary = RuntimeError(SECRET)
    if secondary_error:
        boundary.errors["aux-stop"] = RuntimeError("secondary cleanup error")
    if body == "error":
        stopped.error = primary
    async with running(boundary) as task:
        await stopped.wait_entered.wait()
        if body == "cancel":
            task.cancel("original body cancellation")
        else:
            stopped.set()
        await boundary.entered[phase].wait()
        await assert_reserved_and_unavailable(boundary)
        for index in range(cancel_count):
            task.cancel(f"cleanup cancellation {index}")
            # Let the caller receive each cancellation while its owner remains gated.
            checkpoint = asyncio.Event()
            asyncio.get_running_loop().call_soon(checkpoint.set)
            await checkpoint.wait()
            assert not task.done(), "run must join all cleanup before propagating cancellation"
            assert boundary.interruption is None, "caller cancellation must not reach a stopper"
            await assert_reserved_and_unavailable(boundary)
        boundary.release[phase].set()
        with pytest.raises(RuntimeError if body == "error" else asyncio.CancelledError) as raised:
            await task
        if body == "error":
            assert raised.value is primary
        elif body == "cancel":
            assert raised.value is stopped.interruption
            assert raised.value.args == ("original body cancellation",)
        else:
            assert raised.value is delivered_cancellations[0]
            assert raised.value.args == ("cleanup cancellation 0",)
        assert boundary.events[-5:] == [
            "aux-stop",
            "aux-finished",
            "stop",
            "resources-clean",
            "disconnect",
        ]
        assert all(boundary.events.count(p) == 1 for p in boundary.events[-5:])
        assert boundary.bus.shared.owner is None and boundary.calls == []
        assert boundary.bus.interface is not None
        await unavailable(asyncio.create_task(exported_call(boundary.bus.interface)))


class CompletingSession(Session):
    async def stop(self) -> None:
        await super().stop()
        self.events.append("session.finished")


@pytest.mark.parametrize("cancel_count", [1, 3])
async def test_concrete_service_internal_shield_does_not_abandon_cli_name_cleanup(
    cancel_count: int,
    delivered_cancellations: list[asyncio.CancelledError],
) -> None:
    boundary = CleanupBoundary()
    stopped = BodyStopEvent()
    worker = Worker(boundary.events)
    session = CompletingSession(boundary.events)
    gate = asyncio.Event()
    session.stop_gate = gate
    service = NagaService(
        lambda: (connection(),),
        default_configuration,
        worker,
        lambda _connection, _configuration: session,
    )
    baseline = asyncio.all_tasks()
    task = asyncio.create_task(
        run(
            service,
            install_signal_handler=lambda handled, callback: None,
            stop_event=stopped,
            bus_factory=boundary.connect,
            topology_watcher=boundary.watcher,
            openrazer_lifecycle=CleanupAuxiliary(boundary),
        )
    )
    try:
        async with asyncio.timeout(2):
            await stopped.wait_entered.wait()
            stopped.set()
            await session.stopping.wait()
            for index in range(cancel_count):
                task.cancel(f"concrete cleanup cancellation {index}")
                checkpoint = asyncio.Event()
                asyncio.get_running_loop().call_soon(checkpoint.set)
                await checkpoint.wait()
                assert not task.done(), "internally shielded service.stop must remain joined by CLI"
                assert "session.finished" not in boundary.events
                assert "worker.stop" not in boundary.events
                await assert_reserved_and_unavailable(boundary)
            gate.set()
            with pytest.raises(asyncio.CancelledError) as raised:
                await task
            assert raised.value is delivered_cancellations[0]
            assert raised.value.args == ("concrete cleanup cancellation 0",)
            assert boundary.events.count("session.finished") == 1
            assert boundary.events.count("worker.stop") == 1
            assert boundary.events.count("disconnect") == 1
            assert boundary.events.index("session.finished") < boundary.events.index("worker.stop")
            assert boundary.events.index("worker.stop") < boundary.events.index("disconnect")
            assert boundary.bus.shared.owner is None
            assert not (asyncio.all_tasks() - baseline)
    finally:
        gate.set()
        stopped.set()
        for release in boundary.release.values():
            release.set()
        if not task.done():
            task.cancel()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=2)
        await asyncio.wait_for(asyncio.gather(service.stop(), return_exceptions=True), timeout=2)
