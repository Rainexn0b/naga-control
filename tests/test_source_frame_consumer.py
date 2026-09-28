from dataclasses import replace

import pytest

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
from naga_control.domain.actions import MouseButtonAction
from naga_control.domain.defaults import default_configuration
from naga_control.domain.intents import DeviceActionIntent, KeyOutputIntent, MouseButtonOutputIntent
from naga_control.domain.profiles import Binding, Profile, as_logical_control
from naga_control.service.action_dispatcher import ActionDispatcher
from naga_control.service.frame_planner import FramePlanner
from naga_control.service.source_forwarding import SourceActivationError
from naga_control.service.source_frame_consumer import SourceFrameConsumer


class Source:
    def __init__(self) -> None:
        self.grabbed = False
        self.closed = False

    def revalidate(self) -> None:
        pass

    def drain_pending_frames(self) -> None:
        pass

    def active_keys(self) -> tuple[int, ...]:
        return ()

    def grab(self) -> None:
        self.grabbed = True

    def ungrab(self) -> None:
        self.grabbed = False

    def close(self) -> None:
        self.closed = True


class Proxy:
    def __init__(self) -> None:
        self.events: list[tuple[int, int, int] | str] = []
        self.closed = False

    def write(self, event_type: int, code: int, value: int) -> None:
        self.events.append((event_type, code, value))

    def flush(self) -> None:
        self.events.append("flush")

    def close(self) -> None:
        self.closed = True


class Keyboard:
    def __init__(self) -> None:
        self.intents: list[KeyOutputIntent] = []
        self.released = False

    def emit(self, intent: KeyOutputIntent) -> None:
        self.intents.append(intent)

    def release_all(self) -> None:
        self.released = True

    def close(self) -> None:
        pass


class Mouse:
    def __init__(self) -> None:
        self.intents: list[MouseButtonOutputIntent] = []
        self.released = False

    def emit(self, intent: MouseButtonOutputIntent) -> None:
        self.intents.append(intent)

    def release_all(self) -> None:
        self.released = True

    def close(self) -> None:
        pass


class Actions:
    def __init__(self) -> None:
        self.intents: list[DeviceActionIntent] = []

    def submit(self, intent: DeviceActionIntent) -> bool:
        self.intents.append(intent)
        return True


def test_f13_forwards_boundary_and_submits_dpi_action() -> None:
    consumer, proxy, _, actions, _, _ = _consumer()
    consumer.start()

    consumer.consume(_frame("dpi_up", 1, 183))

    assert proxy.events == ["flush"]
    assert actions.intents == [DeviceActionIntent("dpi_stage_up")]


def test_f17_writes_held_alt_without_forwarding_its_scan_or_key() -> None:
    consumer, proxy, keyboard, _, _, _ = _consumer()
    consumer.start()

    consumer.consume(_frame("ring_finger", 1, 187))
    consumer.consume(_frame("ring_finger", 0, 187))

    assert keyboard.intents == [KeyOutputIntent("left_alt", 1), KeyOutputIntent("left_alt", 0)]
    assert proxy.events == ["flush", "flush"]


def test_unsafe_frame_releases_outputs_and_closes_the_source() -> None:
    consumer, _, keyboard, _, source, mouse = _consumer()
    consumer.start()
    consumer.consume(_frame("ring_finger", 1, 187))
    malformed = ParsedFrame(
        (RawInputEvent(EV_KEY, 187, 0),),
        (LogicalControlEvent(as_logical_control("ring_finger"), 0, 4),),
    )

    with pytest.raises(SourceActivationError):
        consumer.consume(malformed)

    assert keyboard.released
    assert mouse.released
    assert source.closed


def test_mouse_button_mapping_writes_held_output_without_forwarding_source_key() -> None:
    consumer, proxy, _, _, _, mouse = _consumer(profile=_mouse_profile())
    consumer.start()

    consumer.consume(_frame("side_2_front", 1, 30))
    consumer.consume(_frame("side_2_front", 0, 30))

    assert mouse.intents == [MouseButtonOutputIntent("back", 1), MouseButtonOutputIntent("back", 0)]
    assert proxy.events == ["flush", "flush"]


def _consumer(
    *, profile: Profile | None = None
) -> tuple[SourceFrameConsumer, Proxy, Keyboard, Actions, Source, Mouse]:
    source = Source()
    proxy = Proxy()
    keyboard = Keyboard()
    mouse = Mouse()
    actions = Actions()
    planner = FramePlanner(ActionDispatcher(profile or default_configuration().profile("default")))
    return (
        SourceFrameConsumer(planner, source, lambda: proxy, keyboard, mouse, actions),
        proxy,
        keyboard,
        actions,
        source,
        mouse,
    )


def _frame(control: str, value: int, code: int) -> ParsedFrame:
    events = (
        RawInputEvent(EV_MSC, MSC_SCAN, 458860),
        RawInputEvent(EV_KEY, code, value),
        RawInputEvent(EV_SYN, SYN_REPORT, 0),
    )
    return ParsedFrame(events, (LogicalControlEvent(as_logical_control(control), value, 1, 0),))


def _mouse_profile() -> Profile:
    original = default_configuration().profile("default")
    return replace(
        original,
        plate_layout=2,
        bindings=replace(
            original.bindings,
            plate_2=(Binding(as_logical_control("side_2_front"), MouseButtonAction("back")),),
        ),
    )
