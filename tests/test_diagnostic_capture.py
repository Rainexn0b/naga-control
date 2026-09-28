import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest

from naga_control.adapters.evdev.discovery import EventNode, NagaConnection
from naga_control.diagnostics.capture import (
    EV_MSC,
    EV_SYN,
    MSC_SCAN,
    SYN_REPORT,
    EventRecord,
    FrameRecord,
    OpenedSource,
    capture_frames,
    close_sources,
    connection_metadata,
    format_frame,
    open_sources,
)


@dataclass(frozen=True)
class FakeEvent:
    sec: int
    usec: int
    type: int
    code: int
    value: int


@dataclass(frozen=True)
class FakeDeviceInfo:
    bustype: int = 3
    vendor: int = 0x1532
    product: int = 0x00E8
    version: int = 0x0100


class FakeInputDevice:
    name = "Razer Naga V3 Pro"
    phys = "usb-secret/input2"
    uniq = "serial-secret"
    info = FakeDeviceInfo()
    fd = 123

    def __init__(self, events: tuple[FakeEvent, ...], *, disconnect: bool = False) -> None:
        self._events = events
        self._disconnect = disconnect
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def input_props(self, verbose: bool = False) -> list[int]:
        assert not verbose
        return [0]

    def capabilities(self, verbose: bool = False, absinfo: bool = True) -> dict[int, list[int]]:
        assert not verbose
        assert absinfo
        return {1: [30], EV_MSC: [MSC_SCAN]}

    async def async_read_loop(self) -> AsyncIterator[FakeEvent]:
        for event in self._events:
            await asyncio.sleep(0)
            yield event
        if self._disconnect:
            raise OSError("device removed")
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_capture_reads_complete_frames_from_all_sibling_sources() -> None:
    first = _source(
        "interface-00",
        "00",
        FakeInputDevice((_event(1, 30, 1), _event(EV_SYN, SYN_REPORT, 0))),
    )
    second = _source(
        "interface-02",
        "02",
        FakeInputDevice((_event(EV_MSC, MSC_SCAN, 0xD1), _event(EV_SYN, SYN_REPORT, 0))),
    )

    result = await capture_frames((first, second), 0.02)

    assert result.end_reason == "duration elapsed"
    assert {frame.source for frame in result.frames} == {"interface-00", "interface-02"}
    assert all(frame.events[-1].event_type == EV_SYN for frame in result.frames)


@pytest.mark.asyncio
async def test_capture_stops_cleanly_when_source_is_removed() -> None:
    source = _source(
        "interface-02",
        "02",
        FakeInputDevice((_event(1, 30, 1), _event(EV_SYN, SYN_REPORT, 0)), disconnect=True),
    )

    result = await capture_frames((source,), 1.0)

    assert len(result.frames) == 1
    assert result.end_reason.startswith("interface-02 read failed:")


@pytest.mark.asyncio
async def test_disconnect_keeps_complete_frames_already_queued_by_siblings() -> None:
    first = _source(
        "interface-00",
        "00",
        FakeInputDevice((_event(1, 30, 1), _event(EV_SYN, SYN_REPORT, 0)), disconnect=True),
    )
    second = _source(
        "interface-02",
        "02",
        FakeInputDevice((_event(1, 31, 1), _event(EV_SYN, SYN_REPORT, 0)), disconnect=True),
    )

    result = await capture_frames((first, second), 1.0)

    assert {frame.source for frame in result.frames} == {"interface-00", "interface-02"}


def test_metadata_redacts_identifiers_and_labels_capabilities() -> None:
    source = _source("interface-02", "02", FakeInputDevice(()))
    connection = _connection(source.node)

    metadata = connection_metadata(connection, (source,), include_identifiers=False)

    assert metadata["serial"] == "<redacted>"
    assert metadata["physical_path"] == "<redacted>"
    node = metadata["nodes"][0]  # type: ignore[index]
    assert isinstance(node, dict)
    assert node["phys"] == "<redacted>"
    assert node["uniq"] == "<redacted>"
    assert node["capabilities"] == [
        {
            "type": 1,
            "type_name": "EV_KEY",
            "codes": [{"code": 30, "name": "KEY_A"}],
        },
        {
            "type": EV_MSC,
            "type_name": "EV_MSC",
            "codes": [{"code": MSC_SCAN, "name": "MSC_SCAN"}],
        },
    ]


def test_scan_event_format_includes_symbolic_name_and_hex_value() -> None:
    event = EventRecord.from_input(_event(EV_MSC, MSC_SCAN, 0xD2))

    rendered = format_frame(FrameRecord("interface-02", (event,)))

    assert rendered == "interface-02: EV_MSC/MSC_SCAN=210 (0xd2)"


def test_aliased_event_code_has_one_stable_string_name() -> None:
    event = EventRecord.from_input(_event(1, 272, 1))

    assert event.code_name == "BTN_LEFT/BTN_MOUSE"
    assert event.as_json()["code_name"] == "BTN_LEFT/BTN_MOUSE"


def test_open_sources_is_read_only_and_revalidates_open_descriptor() -> None:
    device = FakeInputDevice(())
    connection = _connection(_source("interface-02", "02", device).node)
    calls: list[tuple[str, bool]] = []

    def device_factory(path: str, readonly: bool = False) -> FakeInputDevice:
        calls.append((path, readonly))
        return device

    sources = open_sources(
        connection,
        device_factory=device_factory,
        identity_resolver=lambda _number: connection.nodes[0],
        device_number_resolver=lambda _fd: 456,
    )
    close_sources(sources)

    assert calls == [(connection.nodes[0].event_path, True)]
    assert device.closed


def test_open_sources_rejects_reused_event_path() -> None:
    device = FakeInputDevice(())
    connection = _connection(_source("interface-02", "02", device).node)
    unrelated = EventNode(
        event_path=connection.nodes[0].event_path,
        usb_path="/sys/devices/unrelated",
        interface_number="02",
        vendor_id="1532",
        product_id="00e8",
    )

    with pytest.raises(OSError, match="identity changed"):
        open_sources(
            connection,
            device_factory=lambda path, readonly=False: device,
            identity_resolver=lambda _number: unrelated,
            device_number_resolver=lambda _fd: 456,
        )

    assert device.closed


def _event(event_type: int, code: int, value: int) -> FakeEvent:
    return FakeEvent(10, 20, event_type, code, value)


def _source(source_id: str, interface: str, device: FakeInputDevice) -> OpenedSource:
    node = EventNode(
        event_path=f"/dev/input/event-{interface}",
        usb_path="/sys/devices/usb-secret",
        interface_number=interface,
        vendor_id="1532",
        product_id="00e8",
        serial="serial-secret",
        physical_path="pci-secret",
    )
    return OpenedSource(source_id, node, device)


def _connection(node: EventNode) -> NagaConnection:
    return NagaConnection(
        usb_path=node.usb_path,
        vendor_id=node.vendor_id,
        product_id=node.product_id,
        transport="hyperspeed",
        serial=node.serial,
        physical_path=node.physical_path,
        nodes=(node,),
    )
