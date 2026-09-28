import pytest

from naga_control.adapters.evdev.discovery import EventNode, NagaConnection
from naga_control.adapters.evdev.monitor import NagaDiscoveryMonitor


class FakeMonitor:
    def __init__(self) -> None:
        self.events: list[object] = []
        self.started = False

    def fileno(self) -> int:
        return 123

    def filter_by(self, subsystem: str) -> None:
        assert subsystem == "input"

    def start(self) -> None:
        self.started = True

    def poll(self, timeout: float = 0) -> object | None:
        assert timeout == 0
        return self.events.pop(0) if self.events else None


class FakeLoop:
    def __init__(self) -> None:
        self.callbacks: dict[int, object] = {}
        self.removed: list[int] = []

    def add_reader(self, fd: int, callback: object) -> None:
        self.callbacks[fd] = callback

    def remove_reader(self, fd: int) -> bool:
        self.removed.append(fd)
        return self.callbacks.pop(fd, None) is not None

    def notify(self, fd: int) -> None:
        callback = self.callbacks[fd]
        assert callable(callback)
        callback()


def test_monitor_starts_before_initial_discovery() -> None:
    monitor = FakeMonitor()
    loop = FakeLoop()
    observed_started: list[bool] = []
    discovery = NagaDiscoveryMonitor(
        monitor,
        lambda: _discover_with_state(monitor, observed_started),
    )

    initial = discovery.start(loop)

    assert initial == (_connection(),)
    assert observed_started == [True]
    assert 123 in loop.callbacks


@pytest.mark.asyncio
async def test_monitor_debounces_composite_events_before_rescanning() -> None:
    monitor = FakeMonitor()
    loop = FakeLoop()
    snapshots = [(_connection(),), ()]
    calls = 0

    def discover() -> tuple[NagaConnection, ...]:
        nonlocal calls
        result = snapshots[calls]
        calls += 1
        return result

    discovery = NagaDiscoveryMonitor(monitor, discover, debounce_seconds=0)
    assert discovery.start(loop) == (_connection(),)
    monitor.events.extend((object(), object(), object()))
    loop.notify(123)

    assert await discovery.next_change() == ()
    assert calls == 2


@pytest.mark.asyncio
async def test_close_removes_the_reader_without_triggering_a_rescan() -> None:
    monitor = FakeMonitor()
    loop = FakeLoop()
    discovery = NagaDiscoveryMonitor(monitor, lambda: (_connection(),))
    discovery.start(loop)

    discovery.close()

    assert loop.removed == [123]
    assert await discovery.next_change() is None


def _discover_with_state(
    monitor: FakeMonitor, observed_started: list[bool]
) -> tuple[NagaConnection, ...]:
    observed_started.append(monitor.started)
    return (_connection(),)


def _connection() -> NagaConnection:
    node = EventNode(
        event_path="/dev/input/event5",
        usb_path="/sys/devices/usb-receiver",
        interface_number="02",
        vendor_id="1532",
        product_id="00e8",
    )
    return NagaConnection(
        usb_path=node.usb_path,
        vendor_id=node.vendor_id,
        product_id=node.product_id,
        transport="hyperspeed",
        serial=None,
        physical_path=None,
        nodes=(node,),
    )
