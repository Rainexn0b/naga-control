from collections.abc import AsyncIterator, Collection, Mapping

from naga_control.adapters.evdev.discovery import EventNode
from naga_control.adapters.evdev.frames import (
    EV_KEY,
    EV_MSC,
    EV_SYN,
    MSC_SCAN,
    SYN_REPORT,
    FrameParser,
    ParsedFrame,
    RawControlSignature,
)
from naga_control.service.source_reader import SourceReader


class Event:
    def __init__(self, event_type: int, code: int, value: int) -> None:
        self.type = event_type
        self.code = code
        self.value = value


class Source:
    def __init__(self) -> None:
        self.events = (
            Event(EV_MSC, MSC_SCAN, 458860),
            Event(EV_KEY, 187, 1),
            Event(EV_SYN, SYN_REPORT, 0),
        )

    async def async_read_loop(self) -> AsyncIterator[Event]:
        for event in self.events:
            yield event
        raise OSError("source disconnected")

    def active_keys(self) -> Collection[int]:
        return ()

    def active_abs_values(self) -> Mapping[int, int]:
        return {}


class Sink:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.frames: list[ParsedFrame] = []

    def start(self) -> None:
        self.events.append("start")

    def consume(self, frame: ParsedFrame) -> None:
        self.frames.append(frame)

    def stop(self) -> None:
        self.events.append("stop")


async def test_reader_stops_the_source_lifecycle_after_disconnect_and_reset() -> None:
    sink = Sink()
    reader = SourceReader(Source(), _parser(), sink)

    result = await reader.run()

    assert result.error is not None
    assert str(result.error) == "source disconnected"
    assert sink.events == ["start", "stop"]
    assert [frame.reset_controls for frame in sink.frames] == [(), ("ring_finger",)]


def _parser() -> FrameParser:
    node = EventNode(
        event_path="/dev/input/event5",
        usb_path="/sys/devices/usb-receiver",
        interface_number="01",
        vendor_id="1532",
        product_id="00e8",
    )
    signature = RawControlSignature("00e8", "01", EV_KEY, 187, 458860)
    return FrameParser(node, {signature: "ring_finger"})
