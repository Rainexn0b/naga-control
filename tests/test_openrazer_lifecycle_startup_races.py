import asyncio
from collections.abc import Coroutine

import pytest
from test_openrazer_lifecycle_monitor import FakeProvider
from test_openrazer_lifecycle_startup import (
    RULES,
    Bus,
    Controller,
    assert_detached,
    cleanup_start,
    make_monitor,
)

from naga_control.adapters.openrazer import lifecycle_monitor
from naga_control.adapters.openrazer.lifecycle_monitor import OpenRazerLifecycleMonitor


class SuccessfulAddBus(Bus):
    async def add_match(self, rule: str) -> None:
        self.added.append(rule)
        self.installed.add(rule)
        if len(self.added) - 1 == self.blocked_index:
            self.entered.set()
            await self.release.wait()


class BlockedRemovalBus(Bus):
    def __init__(self, *, retain_handler: bool = False) -> None:
        super().__init__(2, "handler" if retain_handler else "")
        self.removal_entered = asyncio.Event()
        self.removal_release = asyncio.Event()
        self.emit_during_removal = retain_handler
        self.emissions = 0

    async def remove_match(self, rule: str) -> None:
        self.events.append("remove-match")
        self.removed.append(rule)
        if self.emit_during_removal:
            self.emit()
            self.emissions += 1
        self.removal_entered.set()
        await self.removal_release.wait()
        if self.emit_during_removal:
            self.emit()
            self.emissions += 1
        self.installed.remove(rule)


async def test_stop_during_factory_rejects_and_disconnects_the_late_returned_bus() -> None:
    bus = Bus()
    provider = FakeProvider([()])
    controller = Controller(bus.events)
    entered, release = asyncio.Event(), asyncio.Event()

    async def factory() -> Bus:
        entered.set()
        await release.wait()
        return bus

    monitor = OpenRazerLifecycleMonitor(provider, controller, bus_factory=factory)
    start = asyncio.create_task(monitor.start())
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        await asyncio.wait_for(monitor.stop(), timeout=2)
        assert not start.done()
        assert bus.disconnects == 0
        release.set()
        with pytest.raises(RuntimeError, match="stopped"):
            async with asyncio.timeout(2):
                await start
        assert bus.handlers == bus.added == bus.removed == []
        assert bus.events == ["disconnect"]
        assert bus.disconnects == 1
        assert provider.calls == controller.stale_marks == controller.rescans == 0
        await monitor.stop()
        assert bus.disconnects == 1
    finally:
        release.set()
        await cleanup_start(start, monitor)


@pytest.mark.parametrize("blocked_index", [0, 2], ids=["first", "later"])
async def test_stop_during_add_match_rejects_late_success_without_more_startup_work(
    blocked_index: int,
) -> None:
    bus = SuccessfulAddBus(blocked_index)
    provider = FakeProvider([()])
    controller = Controller(bus.events)
    monitor = make_monitor(bus, provider, controller)
    start = asyncio.create_task(monitor.start())
    try:
        await asyncio.wait_for(bus.entered.wait(), timeout=2)
        attempted = list(RULES[: blocked_index + 1])
        await asyncio.wait_for(monitor.stop(), timeout=2)
        assert not start.done()
        assert bus.added == attempted
        assert_detached(bus)
        events = list(bus.events)

        bus.release.set()
        with pytest.raises(RuntimeError, match="stopped"):
            async with asyncio.timeout(2):
                await start
        assert bus.added == attempted
        assert bus.events == events
        assert provider.calls == controller.stale_marks == controller.rescans == 0
        await monitor.stop()
        assert bus.events == events
    finally:
        bus.release.set()
        await cleanup_start(start, monitor)


async def test_retained_handler_signals_during_remove_match_cannot_request_rescans() -> None:
    bus = BlockedRemovalBus(retain_handler=True)
    provider = FakeProvider([()])
    controller = Controller(bus.events)
    monitor = make_monitor(bus, provider, controller)
    start = asyncio.create_task(monitor.start())
    try:
        await asyncio.wait_for(bus.entered.wait(), timeout=2)
        bus.release.set()
        await asyncio.wait_for(bus.removal_entered.wait(), timeout=2)
        assert bus.handlers and bus.emissions == 1
        assert provider.calls == controller.stale_marks == controller.rescans == 0
        assert getattr(monitor, "_runner", None) is None
        bus.removal_release.set()
        with pytest.raises(RuntimeError) as raised:
            async with asyncio.timeout(2):
                await start
        assert raised.value is bus.error
        assert bus.emissions == 2 * len(RULES)
        assert bus.removed == list(reversed(RULES))
        assert bus.disconnects == 1
        assert provider.calls == controller.stale_marks == controller.rescans == 0
        assert getattr(monitor, "_runner", None) is None
    finally:
        bus.removal_release.set()
        await cleanup_start(start, monitor)


async def test_same_tick_signal_runner_is_cancelled_before_provider_or_controller_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SignalThenFailureBus(Bus):
        async def add_match(self, rule: str) -> None:
            self.added.append(rule)
            self.installed.add(rule)
            self.emit()
            raise self.error

    bus = SignalThenFailureBus()
    provider = FakeProvider([()])
    controller = Controller(bus.events)
    monitor = make_monitor(bus, provider, controller)
    created: list[asyncio.Task[None]] = []
    create_task = asyncio.create_task

    def record_task(coroutine: Coroutine[object, object, None]) -> asyncio.Task[None]:
        task = create_task(coroutine)
        created.append(task)
        return task

    try:
        # No scheduling point separates the signal from the startup failure.
        with monkeypatch.context() as patch:
            patch.setattr(lifecycle_monitor.asyncio, "create_task", record_task)
            with pytest.raises(RuntimeError) as raised:
                async with asyncio.timeout(2):
                    await monitor.start()
        assert raised.value is bus.error
        assert len(created) == 1
        assert created[0].done() and created[0].cancelled()
        assert controller.stale_marks == 1
        assert provider.calls == controller.rescans == 0
        assert not controller.entered.is_set()
        assert_detached(bus)
    finally:
        await asyncio.wait_for(monitor.stop(), timeout=2)
        for task in created:
            if not task.done():
                task.cancel()
        await asyncio.wait_for(asyncio.gather(*created, return_exceptions=True), timeout=2)


async def test_second_cancellation_during_rollback_remove_match_still_disconnects() -> None:
    bus = BlockedRemovalBus()
    provider = FakeProvider([()])
    controller = Controller(bus.events)
    monitor = make_monitor(bus, provider, controller)
    start = asyncio.create_task(monitor.start())
    try:
        await asyncio.wait_for(bus.entered.wait(), timeout=2)
        start.cancel("interrupt AddMatch")
        await asyncio.wait_for(bus.removal_entered.wait(), timeout=2)
        start.cancel("interrupt RemoveMatch cleanup")
        with pytest.raises(asyncio.CancelledError):
            async with asyncio.timeout(2):
                await start
        # A second cancellation may replace the first; remaining rules need not
        # get RemoveMatch replies, but disconnect and ownership reset are mandatory.
        assert bus.disconnects == 1
        assert bus.events[-1] == "disconnect"
        assert bus.handlers == []
        assert getattr(monitor, "_bus", None) is None
        assert getattr(monitor, "_subscribed_rules", None) == []
        assert getattr(monitor, "_handler_added", None) is False
        assert provider.calls == controller.stale_marks == controller.rescans == 0
        events = list(bus.events)
        await monitor.stop()
        await monitor.stop()
        assert bus.events == events
    finally:
        bus.removal_release.set()
        await cleanup_start(start, monitor)
