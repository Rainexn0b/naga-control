"""Fake-only CLI shutdown integration for PrepareShutdown/Exit."""

import asyncio
import inspect
from collections.abc import Callable, Coroutine
from typing import cast

import pytest
from dbus_next.constants import NameFlag, RequestNameReply
from dbus_next.errors import DBusError

from naga_control.domain.hardware import HardwareState
from naga_control.service.service_cli import run

ERROR_TYPE = "org.nagacontrol.Service1.Error.Unavailable"
SECRET = "SECRET_SERIAL /private/usb/port"


class MethodMetadata:
    fn: Callable[..., Coroutine[object, object, object]]


def call(interface: object, name: str) -> Coroutine[object, object, object]:
    raw = vars(type(interface))[name]
    metadata = cast(MethodMetadata, vars(raw)["__DBUS_METHOD"])
    result = metadata.fn(interface)
    assert inspect.isawaitable(result)
    return result


async def unavailable(task: asyncio.Task[object]) -> None:
    with pytest.raises(DBusError) as raised:
        await task
    assert raised.value.type == ERROR_TYPE  # type: ignore[attr-defined]
    assert SECRET not in str(raised.value)
    assert raised.value.__cause__ is None


class FakeService:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.start_entered = asyncio.Event()
        self.start_release = asyncio.Event()
        self.start_release.set()
        self.stop_calls = 0
        self.stop_error: Exception | None = None
        self.stop_entered = asyncio.Event()
        self.stop_release = asyncio.Event()
        self.stop_release.set()

    async def start(self) -> HardwareState:
        self.events.append("service-start")
        self.start_entered.set()
        await self.start_release.wait()
        return HardwareState("absent", 1)

    async def stop(self) -> None:
        self.stop_calls += 1
        self.events.append("service-stop")
        self.stop_entered.set()
        await self.stop_release.wait()
        if self.stop_error is not None:
            raise self.stop_error

    def snapshot(self) -> dict[str, object]:
        return {"status": "available"}

    def release_all(self) -> None:
        pass

    def configuration_document(self) -> str:
        return ""

    def configuration_revision(self) -> int:
        return 0

    async def apply_configuration(self, expected_revision: int, document: str) -> int:
        return 0

    async def select_profile(self, profile_id: str) -> int:
        return 0

    async def begin_calibration(self) -> bool:
        return True

    async def end_calibration(self) -> bool:
        return False


class FakeAux:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def start(self) -> None:
        self.events.append("aux-start")

    async def stop(self) -> None:
        self.events.append("aux-stop")


class FakeBus:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.interface: object | None = None

    def export(self, path: str, interface: object) -> None:
        self.events.append("export")
        self.interface = interface

    async def request_name(self, name: str, flags: NameFlag = NameFlag.NONE) -> object:
        self.events.append("name")
        assert flags == NameFlag.DO_NOT_QUEUE
        return RequestNameReply.PRIMARY_OWNER

    def disconnect(self) -> None:
        self.events.append("disconnect")


class LossyBus(FakeBus):
    def __init__(self, events: list[str]) -> None:
        super().__init__(events)
        self.loss = asyncio.Event()

    async def wait_for_disconnect(self) -> None:
        await self.loss.wait()


async def start_running(
    events: list[str],
    service: FakeService,
    bus: FakeBus,
    stopped: asyncio.Event,
    watcher_entered: asyncio.Event,
) -> asyncio.Task[None]:
    aux = FakeAux(events)

    async def watcher() -> None:
        events.append("watcher-start")
        watcher_entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            events.append("watcher-stop")

    task = asyncio.create_task(
        run(
            service,
            install_signal_handler=lambda handled, callback: None,
            stop_event=stopped,
            bus_factory=lambda: _bus(bus),
            topology_watcher=watcher,
            openrazer_lifecycle=aux,
        )
    )
    return task


async def _bus(bus: FakeBus) -> FakeBus:
    return bus


async def stop_task(task: asyncio.Task[None]) -> None:
    if not task.done():
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_prepare_then_exit_releases_in_order_without_disconnecting_early() -> None:
    events: list[str] = []
    service = FakeService(events)
    bus = FakeBus(events)
    stopped = asyncio.Event()
    watcher_entered = asyncio.Event()
    task = await start_running(events, service, bus, stopped, watcher_entered)
    try:
        await asyncio.wait_for(watcher_entered.wait(), timeout=2)
        assert bus.interface is not None
        assert "disconnect" not in events
        await call(bus.interface, "PrepareShutdown")
        assert events.count("service-stop") == 1
        assert events.count("aux-stop") == 1
        assert events.count("watcher-stop") == 1
        assert events.index("watcher-stop") < events.index("aux-stop")
        assert events.index("aux-stop") < events.index("service-stop")
        assert "disconnect" not in events
        await unavailable(asyncio.create_task(call(bus.interface, "GetSnapshot")))
        await call(bus.interface, "PrepareShutdown")
        assert events.count("service-stop") == 1
        await call(bus.interface, "Exit")
        async with asyncio.timeout(2):
            await task
    finally:
        await stop_task(task)
    assert events.count("disconnect") == 1
    assert events.count("service-stop") == 1
    assert events[-1] == "disconnect"


async def test_exit_before_prepare_is_rejected_while_running() -> None:
    events: list[str] = []
    service = FakeService(events)
    bus = FakeBus(events)
    stopped = asyncio.Event()
    watcher_entered = asyncio.Event()
    task = await start_running(events, service, bus, stopped, watcher_entered)
    try:
        await asyncio.wait_for(watcher_entered.wait(), timeout=2)
        assert bus.interface is not None
        await unavailable(asyncio.create_task(call(bus.interface, "Exit")))
        assert service.stop_calls == 0 and "disconnect" not in events
        stopped.set()
        async with asyncio.timeout(2):
            await task
    finally:
        await stop_task(task)
    assert events.count("disconnect") == 1


async def test_prepare_failure_is_terminal_and_exit_stays_refused() -> None:
    events: list[str] = []
    service = FakeService(events)
    original = RuntimeError(SECRET)
    service.stop_error = original
    bus = FakeBus(events)
    stopped = asyncio.Event()
    watcher_entered = asyncio.Event()
    task = await start_running(events, service, bus, stopped, watcher_entered)
    try:
        await asyncio.wait_for(watcher_entered.wait(), timeout=2)
        assert bus.interface is not None
        await unavailable(asyncio.create_task(call(bus.interface, "PrepareShutdown")))
        await unavailable(asyncio.create_task(call(bus.interface, "PrepareShutdown")))
        assert service.stop_calls == 1
        await unavailable(asyncio.create_task(call(bus.interface, "Exit")))
        stopped.set()
        with pytest.raises(RuntimeError) as raised:
            async with asyncio.timeout(2):
                await task
        assert raised.value is original
    finally:
        await stop_task(task)
    assert events.count("disconnect") == 1
    assert service.stop_calls == 1


async def test_concurrent_prepare_with_cancellation_stops_once() -> None:
    events: list[str] = []
    service = FakeService(events)
    service.stop_release = asyncio.Event()
    bus = FakeBus(events)
    stopped = asyncio.Event()
    watcher_entered = asyncio.Event()
    task = await start_running(events, service, bus, stopped, watcher_entered)
    try:
        await asyncio.wait_for(watcher_entered.wait(), timeout=2)
        assert bus.interface is not None
        first = asyncio.create_task(call(bus.interface, "PrepareShutdown"))
        second = asyncio.create_task(call(bus.interface, "PrepareShutdown"))
        await asyncio.wait_for(service.stop_entered.wait(), timeout=2)
        first.cancel("single prepare cancellation")
        with pytest.raises(asyncio.CancelledError):
            await first
        assert not second.done()
        service.stop_release.set()
        async with asyncio.timeout(2):
            await second
        assert service.stop_calls == 1
        stopped.set()
        async with asyncio.timeout(2):
            await task
    finally:
        service.stop_release.set()
        await stop_task(task)
    assert service.stop_calls == 1
    assert events.count("disconnect") == 1


async def test_prepare_before_ready_queues_without_stopping_during_start() -> None:
    events: list[str] = []
    service = FakeService(events)
    service.start_release = asyncio.Event()
    bus = FakeBus(events)
    stopped = asyncio.Event()
    watcher_entered = asyncio.Event()
    task = await start_running(events, service, bus, stopped, watcher_entered)
    try:
        await asyncio.wait_for(service.start_entered.wait(), timeout=2)
        assert bus.interface is not None
        preparing = asyncio.create_task(call(bus.interface, "PrepareShutdown"))
        await asyncio.sleep(0.05)
        assert not preparing.done()
        assert service.stop_calls == 0
        service.start_release.set()
        await asyncio.wait_for(watcher_entered.wait(), timeout=2)
        async with asyncio.timeout(2):
            await preparing
        assert service.stop_calls == 1
        assert "disconnect" not in events
        stopped.set()
        async with asyncio.timeout(2):
            await task
    finally:
        service.start_release.set()
        await stop_task(task)
    assert service.stop_calls == 1


async def test_bus_loss_releases_through_the_same_barrier() -> None:
    events: list[str] = []
    service = FakeService(events)
    bus = LossyBus(events)
    stopped = asyncio.Event()
    watcher_entered = asyncio.Event()
    task = await start_running(events, service, bus, stopped, watcher_entered)
    try:
        await asyncio.wait_for(watcher_entered.wait(), timeout=2)
        bus.loss.set()
        async with asyncio.timeout(2):
            await task
    finally:
        await stop_task(task)
    assert events.count("service-stop") == 1
    assert events.count("disconnect") == 1


async def test_bus_without_disconnect_capability_keeps_prior_behavior() -> None:
    events: list[str] = []
    service = FakeService(events)
    bus = FakeBus(events)
    assert not hasattr(bus, "wait_for_disconnect")
    stopped = asyncio.Event()
    watcher_entered = asyncio.Event()
    task = await start_running(events, service, bus, stopped, watcher_entered)
    try:
        await asyncio.wait_for(watcher_entered.wait(), timeout=2)
        stopped.set()
        async with asyncio.timeout(2):
            await task
    finally:
        await stop_task(task)
    assert events == [
        "export",
        "name",
        "service-start",
        "aux-start",
        "watcher-start",
        "watcher-stop",
        "aux-stop",
        "service-stop",
        "disconnect",
    ]
