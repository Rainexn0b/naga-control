import asyncio
from collections.abc import Callable, Coroutine
from typing import Literal

import pytest
from test_openrazer_lifecycle_monitor import FakeMessage, FakeProvider

from naga_control.adapters.openrazer import lifecycle_monitor
from naga_control.adapters.openrazer.lifecycle_monitor import (
    DEVICE_ADDED_RULE,
    DEVICE_REMOVED_RULE,
    NAME_OWNER_CHANGED_RULE,
    OpenRazerLifecycleMonitor,
)
from naga_control.domain.hardware import HardwareState
from naga_control.ports.hardware import NagaTopology

RULES = (DEVICE_ADDED_RULE, DEVICE_REMOVED_RULE, NAME_OWNER_CHANGED_RULE)
type Failure = Literal["cancel", "error"]


class Bus:
    def __init__(self, blocked_index: int | None = None, teardown_error: str = "") -> None:
        self.blocked_index = blocked_index
        self.teardown_error = teardown_error
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.error = RuntimeError("AddMatch reply failed")
        self.interruption: BaseException | None = None
        self.handlers: list[Callable[[object], bool]] = []
        self.added: list[str] = []
        self.installed: set[str] = set()
        self.removed: list[str] = []
        self.events: list[str] = []
        self.disconnects = 0
        self.saved_handler: Callable[[object], bool] | None = None

    async def add_match(self, rule: str) -> None:
        self.added.append(rule)
        # The daemon can install the rule before its awaited reply reaches us.
        self.installed.add(rule)
        if len(self.added) - 1 == self.blocked_index:
            self.entered.set()
            try:
                await self.release.wait()
                raise self.error
            except BaseException as exc:
                self.interruption = exc
                raise

    async def remove_match(self, rule: str) -> None:
        self.events.append("remove-match")
        self.removed.append(rule)
        if self.teardown_error == "match":
            raise OSError("RemoveMatch failed")
        self.installed.remove(rule)

    def add_message_handler(self, handler: Callable[[object], bool]) -> None:
        self.handlers.append(handler)
        self.saved_handler = handler

    def remove_message_handler(self, handler: Callable[[object], bool]) -> None:
        self.events.append("remove-handler")
        if self.teardown_error == "handler":
            raise OSError("handler removal failed")
        self.handlers.remove(handler)

    def disconnect(self) -> None:
        self.events.append("disconnect")
        self.disconnects += 1
        if self.teardown_error == "disconnect":
            raise OSError("disconnect failed")

    def emit(self) -> None:
        for handler in tuple(self.handlers):
            handler(_message())


class Controller:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.stale_marks = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.runner: asyncio.Task[object] | None = None
        self.rescans = 0
        self.successes = 0
        self.cancelled = False
        self.fence_error: BaseException | None = None

    def mark_topology_stale(self) -> None:
        self.stale_marks += 1
        if self.fence_error is not None:
            raise self.fence_error

    async def rescan(self, connections: tuple[NagaTopology, ...]) -> HardwareState:
        self.runner = asyncio.current_task()
        self.rescans += 1
        self.entered.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            # A suspended finalizer distinguishes cancel() from cancel-and-await.
            await asyncio.sleep(0)
            self.events.append("rescan-finished")
        self.successes += 1
        return HardwareState("absent", self.successes)


def _message() -> FakeMessage:
    return FakeMessage("org.razer", "/org/razer", "razer.devices", "device_added", [])


def make_monitor(
    bus: Bus, provider: FakeProvider, controller: Controller
) -> OpenRazerLifecycleMonitor:
    async def factory() -> Bus:
        return bus

    return OpenRazerLifecycleMonitor(provider, controller, bus_factory=factory, debounce_seconds=0)


async def _interrupt(task: asyncio.Task[None], bus: Bus, failure: Failure) -> None:
    if failure == "cancel":
        task.cancel("interrupted AddMatch reply")
        error_type = asyncio.CancelledError
    else:
        bus.release.set()
        error_type = RuntimeError
    with pytest.raises(error_type) as raised:
        async with asyncio.timeout(2):
            await task
    assert raised.value is bus.interruption
    if failure == "error":
        assert raised.value is bus.error


async def cleanup_start(task: asyncio.Task[None], monitor: OpenRazerLifecycleMonitor) -> None:
    if not task.done():
        task.cancel()
    await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=2)
    await asyncio.wait_for(monitor.stop(), timeout=2)


def assert_detached(bus: Bus) -> None:
    assert bus.handlers == []
    assert bus.removed == list(reversed(bus.added))
    assert bus.installed == set()
    assert bus.events == ["remove-handler", *(["remove-match"] * len(bus.added)), "disconnect"]
    assert bus.disconnects == 1


@pytest.mark.parametrize("blocked_index", [0, 2], ids=["first", "later"])
@pytest.mark.parametrize("failure", ["cancel", "error"])
async def test_interrupted_subscription_rolls_back_even_the_unacknowledged_rule(
    blocked_index: int,
    failure: Failure,
) -> None:
    bus = Bus(blocked_index)
    provider = FakeProvider([()])
    controller = Controller(bus.events)
    monitor = make_monitor(bus, provider, controller)
    task = asyncio.create_task(monitor.start())
    try:
        await asyncio.wait_for(bus.entered.wait(), timeout=2)
        assert bus.added == list(RULES[: blocked_index + 1])
        assert bus.installed == set(bus.added)
        await _interrupt(task, bus, failure)
        assert_detached(bus)
        assert provider.calls == controller.rescans == controller.stale_marks == 0
    finally:
        await cleanup_start(task, monitor)


@pytest.mark.parametrize("failure", ["cancel", "error"])
async def test_owned_startup_failure_is_terminal_and_stop_is_idempotent(failure: Failure) -> None:
    bus = Bus(0)
    monitor = make_monitor(bus, FakeProvider([()]), Controller(bus.events))
    task = asyncio.create_task(monitor.start())
    try:
        await asyncio.wait_for(bus.entered.wait(), timeout=2)
        await _interrupt(task, bus, failure)
        with pytest.raises(RuntimeError, match="stopped"):
            await monitor.start()
        events = list(bus.events)
        await monitor.stop()
        await monitor.stop()
        assert bus.events == events
        assert_detached(bus)
    finally:
        await cleanup_start(task, monitor)


@pytest.mark.parametrize("failure", ["cancel", "error"])
async def test_partial_startup_signal_rescan_is_cancelled_and_awaited_before_detach(
    failure: Failure,
) -> None:
    bus = Bus(2)
    provider = FakeProvider([()])
    controller = Controller(bus.events)
    monitor = make_monitor(bus, provider, controller)
    task = asyncio.create_task(monitor.start())
    try:
        await asyncio.wait_for(bus.entered.wait(), timeout=2)
        bus.emit()
        assert controller.stale_marks == 1
        assert provider.calls == 0
        await asyncio.wait_for(controller.entered.wait(), timeout=2)
        runner = controller.runner
        assert runner is not None and not runner.done()
        await _interrupt(task, bus, failure)
        assert controller.cancelled
        assert runner.done() and runner.cancelled()
        assert bus.events.pop(0) == "rescan-finished"
        assert_detached(bus)
        assert controller.successes == 0

        assert bus.saved_handler is not None
        bus.emit()
        assert bus.saved_handler(_message()) is False
        await asyncio.sleep(0)
        assert controller.stale_marks == provider.calls == controller.rescans == 1
    finally:
        await cleanup_start(task, monitor)


@pytest.mark.parametrize("teardown_error", ["handler", "match", "disconnect"])
@pytest.mark.parametrize("failure", ["cancel", "error"])
async def test_rollback_attempts_all_detach_operations_despite_ordinary_cleanup_errors(
    teardown_error: str,
    failure: Failure,
) -> None:
    bus = Bus(2, teardown_error)
    provider = FakeProvider([()])
    controller = Controller(bus.events)
    monitor = make_monitor(bus, provider, controller)
    task = asyncio.create_task(monitor.start())
    try:
        await asyncio.wait_for(bus.entered.wait(), timeout=2)
        await _interrupt(task, bus, failure)
        assert bus.removed == list(reversed(RULES))
        assert bus.events == [
            "remove-handler",
            "remove-match",
            "remove-match",
            "remove-match",
            "disconnect",
        ]
        assert bus.disconnects == 1
        assert bus.saved_handler is not None
        bus.emit()
        bus.saved_handler(_message())
        await asyncio.sleep(0)
        assert controller.stale_marks == provider.calls == controller.rescans == 0
        events = list(bus.events)
        await monitor.stop()
        await monitor.stop()
        assert bus.events == events
    finally:
        await cleanup_start(task, monitor)


@pytest.mark.parametrize("boundary", ["fence", "schedule"])
async def test_initial_rescan_scheduling_failure_rolls_back_owned_bus(
    boundary: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = Bus()
    provider = FakeProvider([()])
    controller = Controller(bus.events)
    monitor = make_monitor(bus, provider, controller)
    error = RuntimeError("initial rescan scheduling failed")

    def cannot_schedule(coroutine: Coroutine[object, object, None]) -> asyncio.Task[None]:
        coroutine.close()
        raise error

    try:
        with monkeypatch.context() as patch:
            if boundary == "fence":
                controller.fence_error = error
            else:
                patch.setattr(lifecycle_monitor.asyncio, "create_task", cannot_schedule)
            with pytest.raises(RuntimeError) as raised:
                await monitor.start()
        assert raised.value is error
        assert_detached(bus)
        assert provider.calls == controller.rescans == 0
        with pytest.raises(RuntimeError, match="stopped"):
            await monitor.start()
        events = list(bus.events)
        await monitor.stop()
        assert bus.events == events
    finally:
        await asyncio.wait_for(monitor.stop(), timeout=2)


async def test_factory_cancellation_before_return_does_not_transfer_bus_ownership() -> None:
    bus = Bus()
    entered = asyncio.Event()
    release = asyncio.Event()
    interruption: BaseException | None = None
    calls = 0

    async def factory() -> Bus:
        nonlocal calls, interruption
        calls += 1
        if calls == 1:
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError as exc:
                interruption = exc
                raise
        return bus

    provider = FakeProvider([()])
    controller = Controller(bus.events)
    monitor = OpenRazerLifecycleMonitor(provider, controller, bus_factory=factory)
    task = asyncio.create_task(monitor.start())
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel("factory has not returned")
        with pytest.raises(asyncio.CancelledError) as raised:
            async with asyncio.timeout(2):
                await task
        assert raised.value is interruption
        assert bus.handlers == bus.added == bus.removed == bus.events == []
        assert bus.disconnects == controller.stale_marks == provider.calls == 0
        # A factory-owned connection is not a monitor-owned failed startup.
        await monitor.start()
        assert calls == 2
        assert bus.added == list(RULES)
    finally:
        await cleanup_start(task, monitor)
