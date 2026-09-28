from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace

import pytest

from naga_control.adapters.evdev.discovery import EventNode
from naga_control.adapters.evdev.frames import EV_KEY, EV_MSC, EV_SYN, MSC_SCAN, SYN_REPORT
from naga_control.adapters.evdev.source import EV_ABS, EV_REL, EV_SW, EvdevSource, open_evdev_source


@dataclass(frozen=True)
class FakeEvent:
    type: int
    code: int
    value: int


@dataclass(frozen=True)
class FakeAbsInfo:
    value: int
    min: int = -10
    max: int = 10
    fuzz: int = 0
    flat: int = 0
    resolution: int = 0


@dataclass(frozen=True)
class FakeInfo:
    bustype: int = 3
    vendor: int = 0x1532
    product: int = 0x00E8
    version: int = 1


class FakeDevice:
    fd = 42
    info = FakeInfo()

    def __init__(
        self,
        capabilities: Mapping[int, Sequence[object]],
        *,
        axes: Mapping[int, FakeAbsInfo] | None = None,
        batches: tuple[tuple[FakeEvent, ...], ...] = (),
    ) -> None:
        self._capabilities = capabilities
        self._axes = dict(axes or {})
        self._batches = list(batches)
        self.read_calls = 0
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def grab(self) -> None:
        return None

    def ungrab(self) -> None:
        return None

    def input_props(self, verbose: bool = False) -> Sequence[int]:
        assert not verbose
        return (1, 0)

    def capabilities(
        self, verbose: bool = False, absinfo: bool = True
    ) -> Mapping[int, Sequence[object]]:
        assert not verbose
        assert absinfo
        return self._capabilities

    def active_keys(self) -> tuple[int, ...]:
        return ()

    def active_abs_values(self) -> Mapping[int, int]:
        return {axis: info.value for axis, info in self._axes.items()}

    def absinfo(self, axis: int) -> FakeAbsInfo:
        return self._axes[axis]

    def read(self) -> Iterator[FakeEvent]:
        self.read_calls += 1
        if not self._batches:
            raise BlockingIOError
        return iter(self._batches.pop(0))

    async def async_read_loop(self) -> AsyncIterator[FakeEvent]:
        if False:
            yield FakeEvent(0, 0, 0)


def test_proxy_snapshot_filters_output_capabilities_and_keeps_abs_metadata() -> None:
    axis = FakeAbsInfo(11)
    source = _source(
        FakeDevice(
            {
                EV_SYN: (SYN_REPORT,),
                EV_KEY: (30,),
                EV_REL: (0,),
                EV_ABS: ((0, axis),),
                EV_MSC: (MSC_SCAN,),
                EV_SW: (0,),
                17: (0,),
                20: (0,),
                21: (0,),
            },
            axes={0: axis},
        )
    )

    spec = source.forwarding_proxy_spec

    assert spec.name == "Naga Control Forwarding Proxy 1532:00e8/interface-01"
    assert spec.phys == "naga-control/proxy/1532-00e8/interface-01"
    assert spec.input_props == (0, 1)
    assert spec.capabilities == {
        EV_KEY: (30,),
        EV_REL: (0,),
        EV_ABS: ((0, axis),),
        EV_MSC: (MSC_SCAN,),
        EV_SW: (0,),
    }
    assert source.active_abs_values() == {0: 11}


def test_revalidation_uses_only_physical_usb_identity_fields() -> None:
    node = _node()
    accepted = replace(node, event_path="/dev/input/event99", serial="x", physical_path="y")
    EvdevSource(
        node,
        FakeDevice({}),
        identity_resolver=lambda _fd: accepted,
        device_number_resolver=lambda _fd: 1,
    ).revalidate()

    for invalid in (
        replace(node, usb_path="/sys/devices/other"),
        replace(node, interface_number="02"),
        replace(node, vendor_id="1234"),
        replace(node, product_id="00e7"),
    ):
        source = EvdevSource(
            node,
            FakeDevice({}),
            identity_resolver=lambda _fd, current=invalid: current,
            device_number_resolver=lambda _fd: 1,
        )
        with pytest.raises(OSError, match="identity changed"):
            source.revalidate()


def test_drain_reads_queued_events_until_nonblocking_eagain() -> None:
    device = FakeDevice(
        {},
        batches=((FakeEvent(EV_KEY, 30, 1),), (FakeEvent(EV_SYN, SYN_REPORT, 0),)),
    )

    _source(device).drain_pending_frames()

    assert device.read_calls == 3


def test_open_revalidates_before_building_the_proxy_snapshot_and_closes_on_mismatch() -> None:
    device = FakeDevice({EV_KEY: (30,)})

    with pytest.raises(OSError, match="identity changed"):
        open_evdev_source(
            _node(),
            device_factory=lambda path: device,
            identity_resolver=lambda _number: replace(_node(), interface_number="02"),
            device_number_resolver=lambda _fd: 1,
        )

    assert device.closed


def test_open_returns_a_revalidated_physical_source() -> None:
    device = FakeDevice({EV_KEY: (30,)})

    source = open_evdev_source(
        _node(),
        device_factory=lambda path: device,
        identity_resolver=lambda _number: _node(),
        device_number_resolver=lambda _fd: 1,
    )

    assert source.node == _node()
    assert source.forwarding_proxy_spec.capabilities == {EV_KEY: (30,)}


def _source(device: FakeDevice) -> EvdevSource:
    return EvdevSource(
        _node(),
        device,
        identity_resolver=lambda _fd: _node(),
        device_number_resolver=lambda _fd: 1,
    )


def _node() -> EventNode:
    return EventNode(
        event_path="/dev/input/event5",
        usb_path="/sys/devices/usb-receiver",
        interface_number="01",
        vendor_id="1532",
        product_id="00e8",
        serial="ignored",
        physical_path="ignored",
    )
