from naga_control.adapters.evdev.frames import (
    EV_KEY,
    EV_MSC,
    EV_SYN,
    MSC_SCAN,
    SYN_REPORT,
    LogicalControlEvent,
    ParsedFrame,
    RawInputEvent,
)
from naga_control.domain.defaults import default_configuration
from naga_control.domain.intents import DeviceActionIntent, KeyOutputIntent
from naga_control.domain.profiles import as_logical_control
from naga_control.service.action_dispatcher import ActionDispatcher
from naga_control.service.frame_planner import FramePlanner


def test_f13_suppresses_its_scan_and_key_but_forwards_frame_boundary() -> None:
    plan = _planner().plan(_frame("dpi_up", 1, 183))

    assert plan.forwarded_events == (_event(EV_SYN, SYN_REPORT, 0),)
    assert plan.device_intents == (DeviceActionIntent("dpi_stage_up"),)


def test_f17_down_and_up_emit_left_alt_and_suppress_only_handled_events() -> None:
    planner = _planner()

    down = planner.plan(_frame("ring_finger", 1, 187))
    up = planner.plan(_frame("ring_finger", 0, 187))

    assert down.key_intents == (KeyOutputIntent("left_alt", 1),)
    assert up.key_intents == (KeyOutputIntent("left_alt", 0),)
    assert down.forwarded_events == (_event(EV_SYN, SYN_REPORT, 0),)


def test_unrelated_events_are_forwarded_with_a_handled_control() -> None:
    events = (
        _event(EV_MSC, MSC_SCAN, 458860),
        _event(EV_KEY, 187, 1),
        _event(EV_MSC, MSC_SCAN, 99),
        _event(2, 0, 3),
        _event(EV_SYN, SYN_REPORT, 0),
    )
    frame = ParsedFrame(events, (LogicalControlEvent(as_logical_control("ring_finger"), 1, 1, 0),))

    plan = _planner().plan(frame)

    assert plan.forwarded_events == events[2:]


def test_invalid_provenance_fails_open_and_releases_held_output() -> None:
    planner = _planner()
    planner.plan(_frame("ring_finger", 1, 187))
    malformed = ParsedFrame(
        (_event(EV_KEY, 187, 0), _event(EV_SYN, SYN_REPORT, 0)),
        (LogicalControlEvent(as_logical_control("ring_finger"), 0, 4),),
    )

    plan = planner.plan(malformed)

    assert plan.unsafe
    assert plan.forwarded_events == malformed.events
    assert plan.key_intents == (KeyOutputIntent("left_alt", 0),)


def _planner() -> FramePlanner:
    return FramePlanner(ActionDispatcher(default_configuration().profile("default")))


def _frame(control_id: str, value: int, key_code: int) -> ParsedFrame:
    events = (
        _event(EV_MSC, MSC_SCAN, 458860),
        _event(EV_KEY, key_code, value),
        _event(EV_SYN, SYN_REPORT, 0),
    )
    return ParsedFrame(events, (LogicalControlEvent(as_logical_control(control_id), value, 1, 0),))


def _event(event_type: int, code: int, value: int) -> RawInputEvent:
    return RawInputEvent(event_type, code, value)
