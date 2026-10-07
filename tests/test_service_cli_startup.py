import asyncio
import signal
from collections.abc import Callable
from typing import Literal

import pytest
from dbus_next.constants import NameFlag
from test_service_cli import Bus, Service

from naga_control.domain.hardware import HardwareState
from naga_control.service.service_cli import run


class Auxiliary:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.error = RuntimeError("auxiliary startup failed")
        self.interruption: BaseException | None = None

    async def start(self) -> None:
        self.events.append("auxiliary-start")
        self.entered.set()
        try:
            await self.release.wait()
            raise self.error
        except BaseException as exc:
            self.interruption = exc
            raise

    async def stop(self) -> None:
        self.events.append("auxiliary-stop")


class OrderedService(Service):
    async def start(self) -> HardwareState:
        self.events.append("service-start")
        return HardwareState("absent", 1)

    async def stop(self) -> None:
        self.events.append("service-stop")


class OrderedBus(Bus):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.trace = events

    def export(self, path: str, interface: object) -> None:
        self.trace.append("export")
        super().export(path, interface)

    async def request_name(self, name: str, flags: NameFlag = NameFlag.NONE) -> object:
        self.trace.append("name")
        return await super().request_name(name, flags)

    def disconnect(self) -> None:
        self.trace.append("disconnect")
        super().disconnect()


@pytest.mark.parametrize("failure", ["cancel", "error"])
async def test_run_stops_entered_auxiliary_before_service_then_releases_early_publication(
    failure: Literal["cancel", "error"],
) -> None:
    service = OrderedService()
    auxiliary = Auxiliary(service.events)
    bus = OrderedBus(service.events)
    factory_calls = 0
    watcher_calls = 0
    signals: list[signal.Signals] = []

    async def factory() -> Bus:
        nonlocal factory_calls
        factory_calls += 1
        service.events.append("bus-connect")
        return bus

    async def watcher() -> None:
        nonlocal watcher_calls
        watcher_calls += 1

    def install(handled: signal.Signals, callback: Callable[[], None]) -> None:
        signals.append(handled)

    task = asyncio.create_task(
        run(
            service,
            install_signal_handler=install,
            stop_event=asyncio.Event(),
            bus_factory=factory,
            topology_watcher=watcher,
            openrazer_lifecycle=auxiliary,
        )
    )
    try:
        await asyncio.wait_for(auxiliary.entered.wait(), timeout=2)
        assert service.events == [
            "bus-connect",
            "export",
            "name",
            "service-start",
            "auxiliary-start",
        ]
        if failure == "cancel":
            task.cancel("cancelled inside auxiliary.start")
            error_type = asyncio.CancelledError
        else:
            auxiliary.release.set()
            error_type = RuntimeError
        with pytest.raises(error_type) as raised:
            async with asyncio.timeout(2):
                await task
        assert raised.value is auxiliary.interruption
        if failure == "error":
            assert raised.value is auxiliary.error
        assert signals == [signal.SIGINT, signal.SIGTERM]
        assert factory_calls == 1 and watcher_calls == 0
        assert bus.events == [
            "export:/org/nagacontrol/Service1",
            "name:org.nagacontrol.Service1",
            "disconnect",
        ]
        assert service.events == [
            "bus-connect",
            "export",
            "name",
            "service-start",
            "auxiliary-start",
            "auxiliary-stop",
            "service-stop",
            "disconnect",
        ]
    finally:
        if not task.done():
            task.cancel()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=2)


async def test_run_does_not_stop_an_auxiliary_whose_start_was_never_entered() -> None:
    error = RuntimeError("service startup failed")

    class FailedService(OrderedService):
        async def start(self) -> HardwareState:
            self.events.append("service-start")
            raise error

    service = FailedService()
    auxiliary = Auxiliary(service.events)
    bus = OrderedBus(service.events)
    factory_calls = 0

    async def factory() -> Bus:
        nonlocal factory_calls
        factory_calls += 1
        service.events.append("bus-connect")
        return bus

    with pytest.raises(RuntimeError) as raised:
        await run(
            service,
            install_signal_handler=lambda handled, callback: None,
            bus_factory=factory,
            openrazer_lifecycle=auxiliary,
        )
    assert raised.value is error
    assert not auxiliary.entered.is_set()
    assert service.events == [
        "bus-connect",
        "export",
        "name",
        "service-start",
        "service-stop",
        "disconnect",
    ]
    assert factory_calls == 1
    assert bus.events == [
        "export:/org/nagacontrol/Service1",
        "name:org.nagacontrol.Service1",
        "disconnect",
    ]
