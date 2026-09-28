"""Read and serialize complete evdev frames without grabbing input devices."""

import asyncio
import os
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib import import_module
from typing import Protocol, cast

from naga_control.adapters.evdev.discovery import EventNode, NagaConnection, resolve_event_node

REDACTED = "<redacted>"


class InputEventLike(Protocol):
    @property
    def sec(self) -> int: ...

    @property
    def usec(self) -> int: ...

    @property
    def type(self) -> int: ...

    @property
    def code(self) -> int: ...

    @property
    def value(self) -> int: ...


class AbsInfoLike(Protocol):
    @property
    def value(self) -> int: ...

    @property
    def min(self) -> int: ...

    @property
    def max(self) -> int: ...

    @property
    def fuzz(self) -> int: ...

    @property
    def flat(self) -> int: ...

    @property
    def resolution(self) -> int: ...


class DeviceInfoLike(Protocol):
    @property
    def bustype(self) -> int: ...

    @property
    def vendor(self) -> int: ...

    @property
    def product(self) -> int: ...

    @property
    def version(self) -> int: ...


class InputDeviceLike(Protocol):
    @property
    def fd(self) -> int: ...

    @property
    def name(self) -> str: ...

    @property
    def phys(self) -> str | None: ...

    @property
    def uniq(self) -> str | None: ...

    @property
    def info(self) -> DeviceInfoLike: ...

    def close(self) -> None: ...

    def input_props(self, verbose: bool = False) -> list[int]: ...

    def capabilities(
        self, verbose: bool = False, absinfo: bool = True
    ) -> Mapping[int, Sequence[int | tuple[int, AbsInfoLike]]]: ...

    def async_read_loop(self) -> AsyncIterator[InputEventLike]: ...


class InputDeviceFactory(Protocol):
    def __call__(self, path: str, readonly: bool = False) -> InputDeviceLike: ...


_evdev = import_module("evdev")
_ecodes = import_module("evdev.ecodes")
_input_device_factory = cast(InputDeviceFactory, _evdev.InputDevice)
CodeName = str | Sequence[str]
_event_types = cast(Mapping[int, CodeName], _ecodes.EV)
_input_properties = cast(Mapping[int, CodeName], _ecodes.INPUT_PROP)
_codes_by_type = cast(Mapping[int, Mapping[int, CodeName]], _ecodes.bytype)
EV_SYN = cast(int, _ecodes.EV_SYN)
EV_MSC = cast(int, _ecodes.EV_MSC)
SYN_REPORT = cast(int, _ecodes.SYN_REPORT)
MSC_SCAN = cast(int, _ecodes.MSC_SCAN)


@dataclass(frozen=True, slots=True)
class OpenedSource:
    source_id: str
    node: EventNode
    device: InputDeviceLike


@dataclass(frozen=True, slots=True)
class EventRecord:
    seconds: int
    microseconds: int
    event_type: int
    event_type_name: str
    code: int
    code_name: str
    value: int

    @classmethod
    def from_input(cls, event: InputEventLike) -> "EventRecord":
        return cls(
            seconds=event.sec,
            microseconds=event.usec,
            event_type=event.type,
            event_type_name=_event_type_name(event.type),
            code=event.code,
            code_name=_event_code_name(event.type, event.code),
            value=event.value,
        )

    def as_json(self) -> dict[str, object]:
        return {
            "seconds": self.seconds,
            "microseconds": self.microseconds,
            "type": self.event_type,
            "type_name": self.event_type_name,
            "code": self.code,
            "code_name": self.code_name,
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class FrameRecord:
    source: str
    events: tuple[EventRecord, ...]

    def as_json(self) -> dict[str, object]:
        return {"source": self.source, "events": [event.as_json() for event in self.events]}


@dataclass(frozen=True, slots=True)
class CaptureResult:
    frames: tuple[FrameRecord, ...]
    end_reason: str


@dataclass(frozen=True, slots=True)
class _ReaderFinished:
    source: str
    error: str | None


def open_sources(
    connection: NagaConnection,
    *,
    device_factory: InputDeviceFactory = _input_device_factory,
    identity_resolver: Callable[[int], EventNode] = resolve_event_node,
    device_number_resolver: Callable[[int], int] = lambda fd: os.fstat(fd).st_rdev,
) -> tuple[OpenedSource, ...]:
    """Open every sibling node read-only and assign stable capture identifiers."""
    opened: list[OpenedSource] = []
    interface_counts: dict[str, int] = {}
    try:
        for node in connection.nodes:
            interface_counts[node.interface_number] = (
                interface_counts.get(node.interface_number, 0) + 1
            )
            occurrence = interface_counts[node.interface_number]
            source_id = f"interface-{node.interface_number}"
            if occurrence > 1:
                source_id = f"{source_id}-{occurrence}"
            device = device_factory(node.event_path, readonly=True)
            try:
                current_node = identity_resolver(device_number_resolver(device.fd))
                if not _same_physical_source(node, current_node):
                    raise OSError(f"input identity changed before open: {node.event_path}")
            except BaseException:
                device.close()
                raise
            opened.append(OpenedSource(source_id, node, device))
    except BaseException:
        close_sources(opened)
        raise
    return tuple(opened)


def close_sources(sources: tuple[OpenedSource, ...] | list[OpenedSource]) -> None:
    for source in sources:
        source.device.close()


def connection_metadata(
    connection: NagaConnection,
    sources: tuple[OpenedSource, ...],
    *,
    include_identifiers: bool,
) -> dict[str, object]:
    return {
        "vendor_id": connection.vendor_id,
        "product_id": connection.product_id,
        "transport": connection.transport,
        "serial": _visible(connection.serial, include_identifiers),
        "physical_path": _visible(
            connection.physical_path or connection.usb_path, include_identifiers
        ),
        "nodes": [
            source_metadata(source, include_identifiers=include_identifiers) for source in sources
        ],
    }


def source_metadata(source: OpenedSource, *, include_identifiers: bool) -> dict[str, object]:
    device = source.device
    info = device.info
    properties = device.input_props(verbose=False)
    return {
        "source": source.source_id,
        "interface": source.node.interface_number,
        "name": device.name,
        "phys": _visible(device.phys, include_identifiers),
        "uniq": _visible(device.uniq, include_identifiers),
        "input_id": {
            "bus_type": info.bustype,
            "vendor": info.vendor,
            "product": info.product,
            "version": info.version,
        },
        "properties": [
            {"code": code, "name": _mapping_name(_input_properties, code, "INPUT_PROP")}
            for code in sorted(properties)
        ],
        "capabilities": _capabilities(device),
    }


async def capture_frames(
    sources: tuple[OpenedSource, ...],
    duration: float,
    on_frame: Callable[[FrameRecord], None] | None = None,
) -> CaptureResult:
    """Capture frames until the duration expires or any source disconnects."""
    queue: asyncio.Queue[FrameRecord | _ReaderFinished] = asyncio.Queue()
    tasks = [asyncio.create_task(_read_source(source, queue)) for source in sources]
    frames: list[FrameRecord] = []
    loop = asyncio.get_running_loop()
    deadline = loop.time() + duration
    reason = "duration elapsed"

    try:
        while tasks:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                item = await asyncio.wait_for(queue.get(), timeout=remaining)
            except TimeoutError:
                break
            if isinstance(item, _ReaderFinished):
                reason = item.error or f"{item.source} disconnected"
                break
            frames.append(item)
            if on_frame is not None:
                on_frame(item)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        while not queue.empty():
            item = queue.get_nowait()
            if isinstance(item, FrameRecord):
                frames.append(item)
                if on_frame is not None:
                    on_frame(item)

    return CaptureResult(tuple(frames), reason)


async def _read_source(
    source: OpenedSource,
    queue: asyncio.Queue[FrameRecord | _ReaderFinished],
) -> None:
    current_frame: list[EventRecord] = []
    error: str | None = None
    try:
        async for event in source.device.async_read_loop():
            current_frame.append(EventRecord.from_input(event))
            if event.type == EV_SYN and event.code == SYN_REPORT:
                queue.put_nowait(FrameRecord(source.source_id, tuple(current_frame)))
                current_frame.clear()
    except OSError as exc:
        error = f"{source.source_id} read failed: {exc}"
    finally:
        queue.put_nowait(_ReaderFinished(source.source_id, error))


def format_frame(frame: FrameRecord) -> str:
    parts: list[str] = []
    for event in frame.events:
        value = str(event.value)
        if event.event_type == EV_MSC and event.code == MSC_SCAN:
            value = f"{event.value} (0x{event.value:x})"
        parts.append(f"{event.event_type_name}/{event.code_name}={value}")
    return f"{frame.source}: " + ", ".join(parts)


def _capabilities(device: InputDeviceLike) -> list[dict[str, object]]:
    raw = device.capabilities(absinfo=True)
    result: list[dict[str, object]] = []
    for event_type in sorted(raw):
        codes: list[dict[str, object]] = []
        for item in raw[event_type]:
            if isinstance(item, tuple):
                code, abs_info = item
                entry: dict[str, object] = {
                    "code": code,
                    "name": _event_code_name(event_type, code),
                    "abs_info": {
                        "value": abs_info.value,
                        "minimum": abs_info.min,
                        "maximum": abs_info.max,
                        "fuzz": abs_info.fuzz,
                        "flat": abs_info.flat,
                        "resolution": abs_info.resolution,
                    },
                }
            else:
                code = item
                entry = {"code": code, "name": _event_code_name(event_type, code)}
            codes.append(entry)
        result.append(
            {
                "type": event_type,
                "type_name": _event_type_name(event_type),
                "codes": codes,
            }
        )
    return result


def _visible(value: str | None, include_identifiers: bool) -> str | None:
    if value is None:
        return None
    return value if include_identifiers else REDACTED


def _event_type_name(event_type: int) -> str:
    return _mapping_name(_event_types, event_type, "EV")


def _event_code_name(event_type: int, code: int) -> str:
    return _mapping_name(_codes_by_type.get(event_type, {}), code, "CODE")


def _mapping_name(
    mapping: Mapping[int, CodeName],
    code: int,
    fallback_prefix: str,
) -> str:
    name = mapping.get(code)
    if name is None:
        return f"{fallback_prefix}_{code}"
    if isinstance(name, str):
        return name
    return "/".join(name)


def _same_physical_source(expected: EventNode, current: EventNode) -> bool:
    return (
        expected.usb_path == current.usb_path
        and expected.interface_number == current.interface_number
        and expected.vendor_id == current.vendor_id
        and expected.product_id == current.product_id
    )
