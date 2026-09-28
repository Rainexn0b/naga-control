from collections.abc import AsyncIterator, Collection, Mapping
from dataclasses import dataclass

from naga_control.adapters.evdev.discovery import EventNode
from naga_control.adapters.evdev.frames import EV_KEY, EV_MSC, EV_SYN, MSC_SCAN, SYN_REPORT
from naga_control.application.remapping import create_source_reader
from naga_control.domain.defaults import default_configuration
from naga_control.domain.intents import DeviceActionIntent, KeyOutputIntent, MouseButtonOutputIntent
from naga_control.ports.forwarding import ForwardingProxySpec


@dataclass(frozen=True)
class Event:
    type: int
    code: int
    value: int


class Source:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls
        self.node = EventNode(
            event_path="/dev/input/event5",
            usb_path="/sys/devices/usb-receiver",
            interface_number="01",
            vendor_id="1532",
            product_id="00e8",
        )
        self.forwarding_proxy_spec = ForwardingProxySpec(
            "proxy",
            "naga-control/proxy/test",
            3,
            0x1532,
            0x00E8,
            1,
            (),
            {},
        )

    async def async_read_loop(self) -> AsyncIterator[Event]:
        for event in (
            Event(EV_MSC, MSC_SCAN, 458856),
            Event(EV_KEY, 183, 1),
            Event(EV_SYN, SYN_REPORT, 0),
            Event(EV_KEY, 183, 0),
            Event(EV_SYN, SYN_REPORT, 0),
            Event(EV_MSC, MSC_SCAN, 458860),
            Event(EV_KEY, 187, 1),
            Event(EV_SYN, SYN_REPORT, 0),
            Event(EV_KEY, 187, 0),
            Event(EV_SYN, SYN_REPORT, 0),
        ):
            yield event

    def active_keys(self) -> Collection[int]:
        self._calls.append("keys")
        return ()

    def active_abs_values(self) -> Mapping[int, int]:
        return {}

    def revalidate(self) -> None:
        self._calls.append("revalidate")

    def drain_pending_frames(self) -> None:
        self._calls.append("drain")

    def grab(self) -> None:
        self._calls.append("grab")

    def ungrab(self) -> None:
        self._calls.append("ungrab")

    def close(self) -> None:
        self._calls.append("close-source")


class Proxy:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def write(self, event_type: int, code: int, value: int) -> None:
        self._calls.append(f"write:{event_type}:{code}:{value}")

    def flush(self) -> None:
        self._calls.append("flush")

    def close(self) -> None:
        self._calls.append("close-proxy")


class ProxyFactory:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def create(self, spec: ForwardingProxySpec) -> Proxy:
        assert spec.phys == "naga-control/proxy/test"
        self._calls.append("create-proxy")
        return Proxy(self._calls)


class ReadinessWaiter:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def wait_ready(self, spec: ForwardingProxySpec) -> None:
        assert spec.name == "proxy"
        self._calls.append("wait-ready")


class Keyboard:
    def __init__(self) -> None:
        self.intents: list[KeyOutputIntent] = []
        self.released = False

    def emit(self, intent: KeyOutputIntent) -> None:
        self.intents.append(intent)

    def release_all(self) -> None:
        self.released = True

    def close(self) -> None:
        return None


class Mouse:
    def __init__(self) -> None:
        self.intents: list[MouseButtonOutputIntent] = []
        self.released = False

    def emit(self, intent: MouseButtonOutputIntent) -> None:
        self.intents.append(intent)

    def release_all(self) -> None:
        self.released = True

    def close(self) -> None:
        return None


class DeviceActions:
    def __init__(self) -> None:
        self.intents: list[DeviceActionIntent] = []

    def submit(self, intent: DeviceActionIntent) -> bool:
        self.intents.append(intent)
        return True


async def test_composition_runs_verified_dpi_and_held_alt_paths_through_safe_proxying() -> None:
    calls: list[str] = []
    source = Source(calls)
    keyboard = Keyboard()
    mouse = Mouse()
    actions = DeviceActions()

    reader = create_source_reader(
        source,
        default_configuration().profile("default"),
        keyboard,
        mouse,
        actions,
        ProxyFactory(calls),
        ReadinessWaiter(calls),
    )
    result = await reader.run()

    assert result.error is None
    assert calls[:6] == ["revalidate", "create-proxy", "wait-ready", "drain", "keys", "grab"]
    assert calls.count("flush") == 4
    assert calls[-3:] == ["ungrab", "close-source", "close-proxy"]
    assert keyboard.intents == [KeyOutputIntent("left_alt", 1), KeyOutputIntent("left_alt", 0)]
    assert keyboard.released
    assert mouse.intents == []
    assert mouse.released
    assert actions.intents == [DeviceActionIntent("dpi_stage_up")]
