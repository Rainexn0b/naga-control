from naga_control.adapters.evdev.discovery import EventNode
from naga_control.adapters.evdev.frames import (
    EV_KEY,
    EV_MSC,
    EV_SYN,
    MSC_SCAN,
    SYN_DROPPED,
    SYN_REPORT,
    FrameParser,
    LogicalControlEvent,
    RawControlSignature,
    RawInputEvent,
)


def test_parser_buffers_frames_and_retains_press_mapping_for_release() -> None:
    parser = FrameParser(_node(), {_signature(): "ring_finger"})

    assert parser.push(_event(EV_MSC, MSC_SCAN, 0xD1)) is None
    assert parser.push(_event(EV_KEY, 187, 1)) is None
    pressed = parser.push(_event(EV_SYN, SYN_REPORT, 0))
    assert pressed is not None
    assert pressed.controls == (LogicalControlEvent("ring_finger", 1, 1, 0),)
    assert parser.push(_event(EV_KEY, 187, 0)) is None
    released = parser.push(_event(EV_SYN, SYN_REPORT, 0))

    assert released is not None
    assert released.controls == (LogicalControlEvent("ring_finger", 0, 0),)


def test_parser_requires_the_full_fixture_signature() -> None:
    parser = FrameParser(_node(interface="01"), {_signature(): "dpi_up"})

    parser.push(_event(EV_MSC, MSC_SCAN, 0xD1))
    parser.push(_event(EV_KEY, 187, 1))
    frame = parser.push(_event(EV_SYN, SYN_REPORT, 0))

    assert frame is not None
    assert frame.controls == ()


def test_parser_keeps_mapped_repeat_as_the_original_control() -> None:
    parser = FrameParser(_node(), {_signature(): "ring_finger"})

    parser.push(_event(EV_MSC, MSC_SCAN, 0xD1))
    parser.push(_event(EV_KEY, 187, 1))
    parser.push(_event(EV_SYN, SYN_REPORT, 0))
    parser.push(_event(EV_KEY, 187, 2))
    repeated = parser.push(_event(EV_SYN, SYN_REPORT, 0))

    assert repeated is not None
    assert repeated.controls == (LogicalControlEvent("ring_finger", 2, 0),)


def test_parser_collapses_duplicate_key_down_reports() -> None:
    parser = FrameParser(_node(), {_signature(): "ring_finger"})
    parser.push(_event(EV_MSC, MSC_SCAN, 0xD1))
    parser.push(_event(EV_KEY, 187, 1))
    parser.push(_event(EV_SYN, SYN_REPORT, 0))
    parser.push(_event(EV_KEY, 187, 1))
    duplicate = parser.push(_event(EV_SYN, SYN_REPORT, 0))

    assert duplicate is not None
    assert duplicate.controls == ()


def test_syn_dropped_discards_unreliable_events_and_resets_held_controls() -> None:
    parser = FrameParser(_node(), {_signature(): "ring_finger"})
    parser.push(_event(EV_MSC, MSC_SCAN, 0xD1))
    parser.push(_event(EV_KEY, 187, 1))
    parser.push(_event(EV_SYN, SYN_REPORT, 0))

    assert parser.push(_event(EV_SYN, SYN_DROPPED, 0)) is None
    assert parser.push(_event(EV_KEY, 187, 0)) is None
    recovered = parser.push(_event(EV_SYN, SYN_REPORT, 0))

    assert recovered is not None
    assert recovered.events == ()
    assert recovered.controls == ()
    assert recovered.reset_controls == ("ring_finger",)
    assert recovered.resync_required


def _event(event_type: int, code: int, value: int) -> RawInputEvent:
    return RawInputEvent(event_type, code, value)


def _signature() -> RawControlSignature:
    return RawControlSignature("00e8", "02", EV_KEY, 187, 0xD1)


def _node(*, interface: str = "02") -> EventNode:
    return EventNode(
        event_path="/dev/input/event5",
        usb_path="/sys/devices/usb-receiver",
        interface_number=interface,
        vendor_id="1532",
        product_id="00e8",
    )
