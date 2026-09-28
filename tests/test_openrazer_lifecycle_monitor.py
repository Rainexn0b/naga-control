import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from naga_control.adapters.openrazer.lifecycle_monitor import (
    DEVICE_ADDED_RULE,
    DEVICE_REMOVED_RULE,
    NAME_OWNER_CHANGED_RULE,
    OpenRazerLifecycleMonitor,
)
from naga_control.domain.hardware import HardwareState
from naga_control.ports.hardware import NagaTopology


@dataclass
class FakeMessage:
    sender: str
    path: str
    interface: str
    member: str
    body: list[object]


class FakeBus:
    def __init__(self) -> None:
        self.handlers: list[Callable[[object], bool]] = []
        self.added_rules: list[str] = []
        self.removed_rules: list[str] = []
        self.disconnected = False

    async def add_match(self, rule: str) -> None:
        self.added_rules.append(rule)

    async def remove_match(self, rule: str) -> None:
        self.removed_rules.append(rule)

    def add_message_handler(self, handler: Callable[[object], bool]) -> None:
        self.handlers.append(handler)

    def remove_message_handler(self, handler: Callable[[object], bool]) -> None:
        self.handlers.remove(handler)

    def disconnect(self) -> None:
        self.disconnected = True

    def emit(self, message: FakeMessage) -> None:
        for handler in tuple(self.handlers):
            handler(message)


class FakeProvider:
    def __init__(self, results: list[tuple[NagaTopology, ...] | Exception]) -> None:
        self.results = results
        self.calls = 0

    def get_topology(self) -> tuple[NagaTopology, ...]:
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeController:
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.stale_marks = 0
        self.rescans: list[tuple[NagaTopology, ...]] = []

    def mark_topology_stale(self) -> None:
        self.stale_marks += 1

    async def rescan(self, connections: tuple[NagaTopology, ...]) -> HardwareState:
        self.rescans.append(connections)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("rescan failed")
        return HardwareState(status="absent", generation=len(self.rescans))


async def test_start_subscribes_fixed_rules_and_schedules_an_initial_rescan() -> None:
    bus = FakeBus()
    provider = FakeProvider([()])
    controller = FakeController()
    monitor = _monitor(bus, provider, controller)

    await monitor.start()
    await _settle()
    await monitor.stop()

    assert bus.added_rules == [DEVICE_ADDED_RULE, DEVICE_REMOVED_RULE, NAME_OWNER_CHANGED_RULE]
    assert controller.stale_marks == 1
    assert controller.rescans == [()]


async def test_start_surfaces_bus_connection_failures() -> None:
    provider = FakeProvider([()])
    controller = FakeController()

    async def unavailable_factory() -> FakeBus:
        raise OSError("session bus unavailable")

    monitor = OpenRazerLifecycleMonitor(provider, controller, bus_factory=unavailable_factory)
    try:
        await monitor.start()
    except OSError as exc:
        assert str(exc) == "session bus unavailable"
    else:
        raise AssertionError("expected the bus connection failure to surface")

    assert controller.stale_marks == 0
    assert controller.rescans == []


async def test_burst_signals_are_coalesced_and_message_handler_does_not_rescan_inline() -> None:
    bus = FakeBus()
    provider = FakeProvider([(), ()])
    controller = FakeController()
    monitor = _monitor(bus, provider, controller, debounce_seconds=0.01)
    await monitor.start()
    await _settle()

    bus.emit(_device_message("device_added"))
    bus.emit(_device_message("device_removed"))
    bus.emit(_owner_message("org.razer"))

    assert provider.calls == 1
    assert len(controller.rescans) == 1
    assert controller.stale_marks == 4

    await _settle()
    await monitor.stop()

    assert provider.calls == 2
    assert len(controller.rescans) == 2


async def test_name_owner_change_requires_the_openrazer_service_name() -> None:
    bus = FakeBus()
    provider = FakeProvider([()])
    controller = FakeController()
    monitor = _monitor(bus, provider, controller)
    await monitor.start()
    await _settle()

    bus.emit(_owner_message("org.example.Other"))
    await _settle()
    await monitor.stop()

    assert controller.stale_marks == 1
    assert len(controller.rescans) == 1


async def test_provider_and_rescan_errors_allow_later_lifecycle_signals_to_retry() -> None:
    bus = FakeBus()
    provider = FakeProvider([RuntimeError("topology failed"), (), ()])
    controller = FakeController(failures=1)
    monitor = _monitor(bus, provider, controller)
    await monitor.start()
    await _settle()

    bus.emit(_device_message("device_added"))
    await _settle()
    bus.emit(_device_message("device_removed"))
    await _settle()
    await monitor.stop()

    assert provider.calls == 3
    assert len(controller.rescans) == 2


async def test_stop_cancels_pending_work_and_never_stops_the_hardware_controller() -> None:
    bus = FakeBus()
    provider = FakeProvider([()])
    controller = FakeController()
    monitor = _monitor(bus, provider, controller, debounce_seconds=1)
    await monitor.start()
    await monitor.stop()
    await monitor.stop()

    assert controller.rescans == []
    assert bus.handlers == []
    assert bus.removed_rules == [NAME_OWNER_CHANGED_RULE, DEVICE_REMOVED_RULE, DEVICE_ADDED_RULE]
    assert bus.disconnected


def _monitor(
    bus: FakeBus,
    provider: FakeProvider,
    controller: FakeController,
    *,
    debounce_seconds: float = 0,
) -> OpenRazerLifecycleMonitor:
    async def factory() -> FakeBus:
        return bus

    return OpenRazerLifecycleMonitor(
        provider,
        controller,
        bus_factory=factory,
        debounce_seconds=debounce_seconds,
    )


def _device_message(member: str) -> FakeMessage:
    return FakeMessage("org.razer", "/org/razer", "razer.devices", member, [])


def _owner_message(name: str) -> FakeMessage:
    return FakeMessage(
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        "NameOwnerChanged",
        [name, "old-owner", "new-owner"],
    )


async def _settle() -> None:
    await asyncio.sleep(0.02)
