from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest

from naga_control.adapters.evdev.discovery import EventNode
from naga_control.adapters.evdev.frames import (
    EV_KEY,
    EV_MSC,
    EV_SYN,
    MSC_SCAN,
    SYN_REPORT,
    FrameParser,
    LogicalControlEvent,
    ParsedFrame,
    RawControlSignature,
    RawInputEvent,
)
from naga_control.adapters.evdev.source import read_parsed_frames


@dataclass(frozen=True)
class FakeEvent:
    type: int
    code: int
    value: int


class FakeSource:
    def __init__(
        self,
        events: tuple[FakeEvent, ...],
        *,
        disconnect: bool = False,
        active_keys: tuple[int, ...] = (),
        active_abs_values: tuple[tuple[int, int], ...] = (),
    ) -> None:
        self._events = events
        self._disconnect = disconnect
        self._active_keys = active_keys
        self._active_abs_values = dict(active_abs_values)

    def active_keys(self) -> tuple[int, ...]:
        return self._active_keys

    def active_abs_values(self) -> dict[int, int]:
        return self._active_abs_values

    async def async_read_loop(self) -> AsyncIterator[FakeEvent]:
        for event in self._events:
            yield event
        if self._disconnect:
            raise OSError("device removed")


@pytest.mark.asyncio
async def test_reader_emits_only_complete_frames() -> None:
    frames: list[ParsedFrame] = []
    source = FakeSource(
        (
            FakeEvent(EV_MSC, MSC_SCAN, 0xD1),
            FakeEvent(EV_KEY, 187, 1),
            FakeEvent(EV_SYN, SYN_REPORT, 0),
        )
    )

    result = await read_parsed_frames(source, _parser(), frames.append)

    assert result.error is None
    assert frames == [
        ParsedFrame(
            (
                RawInputEvent(EV_MSC, MSC_SCAN, 0xD1),
                RawInputEvent(EV_KEY, 187, 1),
                RawInputEvent(EV_SYN, SYN_REPORT, 0),
            ),
            (LogicalControlEvent("ring_finger", 1, 1, 0),),
        ),
        ParsedFrame((), (), ("ring_finger",)),
    ]


@pytest.mark.asyncio
async def test_reader_resets_a_held_control_when_the_source_disconnects() -> None:
    frames: list[ParsedFrame] = []
    source = FakeSource(
        (
            FakeEvent(EV_MSC, MSC_SCAN, 0xD1),
            FakeEvent(EV_KEY, 187, 1),
            FakeEvent(EV_SYN, SYN_REPORT, 0),
        ),
        disconnect=True,
    )

    result = await read_parsed_frames(source, _parser(), frames.append)

    assert result.error is not None
    assert str(result.error) == "device removed"
    assert frames[-1].reset_controls == ("ring_finger",)


@pytest.mark.asyncio
async def test_reader_queries_current_keys_after_syn_dropped() -> None:
    frames: list[ParsedFrame] = []
    source = FakeSource(
        (
            FakeEvent(EV_MSC, MSC_SCAN, 0xD1),
            FakeEvent(EV_KEY, 187, 1),
            FakeEvent(EV_SYN, SYN_REPORT, 0),
            FakeEvent(EV_SYN, 3, 0),
            FakeEvent(EV_SYN, SYN_REPORT, 0),
        ),
        active_keys=(187,),
        active_abs_values=((0, 12),),
    )

    await read_parsed_frames(source, _parser(), frames.append)

    assert frames[-1].resync_required
    assert frames[-1].active_key_codes == (187,)
    assert frames[-1].active_abs_values == ((0, 12),)


def _parser() -> FrameParser:
    node = EventNode(
        event_path="/dev/input/event5",
        usb_path="/sys/devices/usb-receiver",
        interface_number="02",
        vendor_id="1532",
        product_id="00e8",
    )
    return FrameParser(node, {RawControlSignature("00e8", "02", EV_KEY, 187, 0xD1): "ring_finger"})
