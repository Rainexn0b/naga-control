"""Shared fakes for reader-failure and cleanup-barrier regressions."""

from collections.abc import AsyncIterator, Collection

from naga_control.adapters.evdev.discovery import EventNode, NagaConnection


def make_node(interface: str) -> EventNode:
    return EventNode(
        event_path=f"/dev/input/event-{interface}",
        usb_path="/sys/devices/fake-physical-usb",
        interface_number=interface,
        vendor_id="1532",
        product_id="00e8",
        serial=None,
        physical_path=None,
    )


def make_connection(interfaces: tuple[str, ...] = ("00", "01", "02")) -> NagaConnection:
    nodes = tuple(make_node(interface) for interface in interfaces)
    return NagaConnection(
        "/sys/devices/fake-physical-usb", "1532", "00e8", "hyperspeed", None, None, nodes
    )


class FakeKeyboard:
    def __init__(self) -> None:
        self.released = False
        self.closed = False
        self.release_calls = 0
        self.close_calls = 0
        self.release_error: Exception | None = None

    def emit(self, intent: object) -> None:
        return None

    def release_all(self) -> None:
        self.release_calls += 1
        self.released = True
        if self.release_error is not None:
            raise self.release_error

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True


class FakeMouse(FakeKeyboard):
    pass


class FakeActions:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def start(self) -> None:
        self.events.append("actions.start")

    async def stop(self) -> None:
        self.events.append("actions.stop")

    def submit(self, intent: object) -> bool:
        return True


class FakeManagedSource:
    """Injectable ManagedSource with ordered call tracking."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.release_error: Exception | None = None
        self.ungrab_error: BaseException | None = None
        self.close_error: Exception | None = None
        self.proxy_error: Exception | None = None
        self.grabbed = False
        self.closed = False

    def release_generated_outputs(self) -> None:
        self.calls.append("release")
        if self.release_error is not None:
            raise self.release_error

    def revalidate(self) -> None:
        self.calls.append("revalidate")

    def drain_pending_frames(self) -> None:
        self.calls.append("drain")

    def active_keys(self) -> Collection[int]:
        return ()

    def grab(self) -> None:
        self.calls.append("grab")
        self.grabbed = True

    def ungrab(self) -> None:
        self.calls.append("ungrab")
        if self.ungrab_error is not None:
            raise self.ungrab_error
        self.grabbed = False

    def close(self) -> None:
        self.calls.append("source-close")
        if self.close_error is not None:
            raise self.close_error
        self.closed = True


class FakeProxy:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.close_error: Exception | None = None
        self.closed = False

    def write(self, event_type: int, code: int, value: int) -> None:
        self.calls.append(f"write:{event_type}:{code}:{value}")

    def flush(self) -> None:
        self.calls.append("flush")

    def close(self) -> None:
        self.calls.append("proxy-close")
        if self.close_error is not None:
            raise self.close_error
        self.closed = True


class HangingSource:
    """Minimal PreparedSource double that never yields events."""

    def __init__(self, node: EventNode) -> None:
        self.node = node
        from naga_control.ports.forwarding import ForwardingProxySpec as Spec

        self.forwarding_proxy_spec = Spec("proxy", "phys", 3, 1, 2, 3, (), {})

    async def async_read_loop(self) -> AsyncIterator[object]:
        import asyncio

        await asyncio.Event().wait()
        yield object()

    def active_keys(self) -> tuple[int, ...]:
        return ()

    def active_abs_values(self) -> dict[int, int]:
        return {}

    def revalidate(self) -> None:
        return None

    def drain_pending_frames(self) -> None:
        return None

    def grab(self) -> None:
        return None

    def ungrab(self) -> None:
        return None

    def close(self) -> None:
        return None
