"""Read physical evdev sources into ordered parsed frames without grabbing."""

import os
from collections.abc import AsyncIterator, Callable, Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from importlib import import_module
from typing import Protocol, cast

from naga_control.adapters.evdev.discovery import EventNode, resolve_event_node
from naga_control.adapters.evdev.frames import FrameParser, ParsedFrame, RawInputEvent
from naga_control.ports.forwarding import ForwardingProxySpec

EV_REL = 2
EV_ABS = 3
EV_SW = 5
_PROXIED_TYPES = frozenset((1, EV_REL, EV_ABS, 4, EV_SW))


class InputEventLike(Protocol):
    @property
    def type(self) -> int: ...

    @property
    def code(self) -> int: ...

    @property
    def value(self) -> int: ...


class AsyncInputSource(Protocol):
    def async_read_loop(self) -> AsyncIterator[InputEventLike]: ...

    def active_keys(self) -> Collection[int]: ...

    def active_abs_values(self) -> Mapping[int, int]: ...


class _InputInfo(Protocol):
    @property
    def bustype(self) -> int: ...

    @property
    def vendor(self) -> int: ...

    @property
    def product(self) -> int: ...

    @property
    def version(self) -> int: ...


class _AbsInfo(Protocol):
    @property
    def value(self) -> int: ...


class PhysicalInputDevice(AsyncInputSource, Protocol):
    @property
    def fd(self) -> int: ...

    @property
    def info(self) -> _InputInfo: ...

    def close(self) -> None: ...
    def grab(self) -> None: ...
    def ungrab(self) -> None: ...
    def input_props(self, verbose: bool = False) -> Sequence[int]: ...
    def capabilities(
        self, verbose: bool = False, absinfo: bool = True
    ) -> Mapping[int, Sequence[object]]: ...
    def absinfo(self, axis: int) -> _AbsInfo: ...
    def read(self) -> Iterator[InputEventLike]: ...


class InputDeviceFactory(Protocol):
    def __call__(self, path: str) -> PhysicalInputDevice: ...


class EvdevSource:
    """A revalidated source descriptor with a filtered forwarding-proxy snapshot."""

    def __init__(
        self,
        node: EventNode,
        device: PhysicalInputDevice,
        *,
        identity_resolver: Callable[[int], EventNode] = resolve_event_node,
        device_number_resolver: Callable[[int], int] = lambda fd: os.fstat(fd).st_rdev,
    ) -> None:
        self._node = node
        self._device = device
        self._identity_resolver = identity_resolver
        self._device_number_resolver = device_number_resolver
        capabilities = _filtered_capabilities(device.capabilities(absinfo=True))
        self._abs_axes = _abs_axis_codes(capabilities.get(EV_ABS, ()))
        info = device.info
        identity = f"{node.vendor_id.lower()}:{node.product_id.lower()}/interface-{node.interface_number.lower()}"
        self.forwarding_proxy_spec = ForwardingProxySpec(
            name=f"Naga Control Forwarding Proxy {identity}",
            phys=f"naga-control/proxy/{identity.replace(':', '-')}",
            bustype=info.bustype,
            vendor=info.vendor,
            product=info.product,
            version=info.version,
            input_props=tuple(sorted(device.input_props(verbose=False))),
            capabilities=capabilities,
        )

    @property
    def node(self) -> EventNode:
        return self._node

    def async_read_loop(self) -> AsyncIterator[InputEventLike]:
        return self._device.async_read_loop()

    def active_keys(self) -> Collection[int]:
        return self._device.active_keys()

    def active_abs_values(self) -> Mapping[int, int]:
        return {axis: self._device.absinfo(axis).value for axis in self._abs_axes}

    def revalidate(self) -> None:
        current = self._identity_resolver(self._device_number_resolver(self._device.fd))
        if not _same_physical_source(self._node, current):
            raise OSError("input identity changed before source activation")

    def drain_pending_frames(self) -> None:
        while True:
            try:
                for _event in self._device.read():
                    pass
            except BlockingIOError:
                return

    def grab(self) -> None:
        self._device.grab()

    def ungrab(self) -> None:
        self._device.ungrab()

    def close(self) -> None:
        self._device.close()


def open_evdev_source(
    node: EventNode,
    *,
    device_factory: InputDeviceFactory | None = None,
    identity_resolver: Callable[[int], EventNode] = resolve_event_node,
    device_number_resolver: Callable[[int], int] = lambda fd: os.fstat(fd).st_rdev,
) -> EvdevSource:
    """Open an already physical-parent-validated node and close the reuse race."""
    factory = device_factory or cast(InputDeviceFactory, import_module("evdev").InputDevice)
    device = factory(node.event_path)
    try:
        current = identity_resolver(device_number_resolver(device.fd))
        if not _same_physical_source(node, current):
            raise OSError("input identity changed while opening source")
        return EvdevSource(
            node,
            device,
            identity_resolver=identity_resolver,
            device_number_resolver=device_number_resolver,
        )
    except Exception:
        device.close()
        raise


@dataclass(frozen=True, slots=True)
class SourceReadResult:
    error: OSError | None


async def read_parsed_frames(
    source: AsyncInputSource,
    parser: FrameParser,
    on_frame: Callable[[ParsedFrame], None],
) -> SourceReadResult:
    """Read one source in order and reset held controls on normal or failed termination."""
    error: OSError | None = None
    try:
        async for event in source.async_read_loop():
            frame = parser.push(RawInputEvent(event.type, event.code, event.value))
            if frame is not None:
                if frame.resync_required:
                    frame = replace(
                        frame,
                        active_key_codes=tuple(sorted(source.active_keys())),
                        active_abs_values=tuple(sorted(source.active_abs_values().items())),
                    )
                on_frame(frame)
    except OSError as exc:
        error = exc
    finally:
        if reset_controls := parser.reset():
            on_frame(ParsedFrame((), (), reset_controls))
    return SourceReadResult(error)


def _filtered_capabilities(raw: Mapping[int, Sequence[object]]) -> Mapping[int, Sequence[object]]:
    return {
        event_type: tuple(raw[event_type]) for event_type in _PROXIED_TYPES if raw.get(event_type)
    }


def _abs_axis_codes(items: Sequence[object]) -> tuple[int, ...]:
    result: list[int] = []
    for item in items:
        if isinstance(item, tuple):
            pair = cast(tuple[object, ...], item)
            if len(pair) == 2 and isinstance(pair[0], int):
                result.append(pair[0])
    return tuple(result)


def _same_physical_source(expected: EventNode, current: EventNode) -> bool:
    return (
        expected.usb_path == current.usb_path
        and expected.interface_number == current.interface_number
        and expected.vendor_id == current.vendor_id
        and expected.product_id == current.product_id
    )
