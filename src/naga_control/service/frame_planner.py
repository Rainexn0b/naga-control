"""Create frame-ordered forwarding plans without performing output I/O."""

import logging
from dataclasses import dataclass

from naga_control.adapters.evdev.frames import (
    EV_KEY,
    EV_MSC,
    MSC_SCAN,
    LogicalControlEvent,
    ParsedFrame,
    RawInputEvent,
)
from naga_control.domain.intents import (
    ActionIntent,
    DeviceActionIntent,
    KeyOutputIntent,
    MouseButtonOutputIntent,
)
from naga_control.service.action_dispatcher import ActionDispatcher

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ForwardingPlan:
    forwarded_events: tuple[RawInputEvent, ...]
    key_intents: tuple[KeyOutputIntent, ...] = ()
    mouse_button_intents: tuple[MouseButtonOutputIntent, ...] = ()
    device_intents: tuple[DeviceActionIntent, ...] = ()
    resync_required: bool = False
    active_key_codes: tuple[int, ...] = ()
    active_abs_values: tuple[tuple[int, int], ...] = ()
    flush_outputs: bool = False
    unsafe: bool = False


class FramePlanner:
    """Suppress only handled scan/key pairs and retain all unrelated source events."""

    def __init__(self, dispatcher: ActionDispatcher) -> None:
        self._dispatcher = dispatcher

    def release_all(self) -> tuple[ActionIntent, ...]:
        """Clear resolved held actions during source or output failure cleanup."""
        return self._dispatcher.release_all()

    def plan(self, frame: ParsedFrame) -> ForwardingPlan:
        logger.debug(
            "frame events=%d controls=%s reset=%s",
            len(frame.events),
            [control.control_id for control in frame.controls],
            frame.resync_required,
        )
        if not _has_valid_provenance(frame):
            return self._unsafe_plan(frame, self._dispatcher.release_all())

        suppressed: set[int] = set()
        intents: list[ActionIntent] = []
        unsafe = False
        for control in frame.controls:
            result = self._dispatcher.dispatch(control.control_id, control.value)
            intents.extend(result.intents)
            if result.handled:
                suppressed.add(control.key_event_index)
                if control.scan_event_index is not None:
                    suppressed.add(control.scan_event_index)
            if result.unsafe:
                unsafe = True
                break
        if unsafe:
            return self._make_plan(frame, intents, suppressed, unsafe=True)

        intents.extend(self._dispatcher.release_controls(frame.reset_controls))
        return self._make_plan(frame, intents, suppressed)

    def _unsafe_plan(self, frame: ParsedFrame, intents: tuple[ActionIntent, ...]) -> ForwardingPlan:
        return self._make_plan(frame, intents, set(), unsafe=True)

    def _make_plan(
        self,
        frame: ParsedFrame,
        intents: list[ActionIntent] | tuple[ActionIntent, ...],
        suppressed: set[int],
        *,
        unsafe: bool = False,
    ) -> ForwardingPlan:
        keys, mouse_buttons, devices = _split_intents(intents)
        return ForwardingPlan(
            forwarded_events=tuple(
                event for index, event in enumerate(frame.events) if index not in suppressed
            ),
            key_intents=keys,
            mouse_button_intents=mouse_buttons,
            device_intents=devices,
            resync_required=frame.resync_required,
            active_key_codes=frame.active_key_codes,
            active_abs_values=frame.active_abs_values,
            flush_outputs=bool(frame.events) or bool(keys) or bool(mouse_buttons),
            unsafe=unsafe,
        )


def _has_valid_provenance(frame: ParsedFrame) -> bool:
    seen_keys: set[int] = set()
    for control in frame.controls:
        if control.key_event_index in seen_keys or not _is_key(frame.events, control):
            return False
        seen_keys.add(control.key_event_index)
        if control.scan_event_index is not None and not _is_scan(frame.events, control):
            return False
    return True


def _is_key(events: tuple[RawInputEvent, ...], control: LogicalControlEvent) -> bool:
    return (
        0 <= control.key_event_index < len(events)
        and events[control.key_event_index].event_type == EV_KEY
    )


def _is_scan(events: tuple[RawInputEvent, ...], control: LogicalControlEvent) -> bool:
    index = control.scan_event_index
    return (
        index is not None
        and 0 <= index < control.key_event_index
        and events[index].event_type == EV_MSC
        and events[index].code == MSC_SCAN
    )


def _split_intents(
    intents: list[ActionIntent] | tuple[ActionIntent, ...],
) -> tuple[
    tuple[KeyOutputIntent, ...],
    tuple[MouseButtonOutputIntent, ...],
    tuple[DeviceActionIntent, ...],
]:
    keys: list[KeyOutputIntent] = []
    mouse_buttons: list[MouseButtonOutputIntent] = []
    devices: list[DeviceActionIntent] = []
    for intent in intents:
        if isinstance(intent, KeyOutputIntent):
            keys.append(intent)
        elif isinstance(intent, MouseButtonOutputIntent):
            mouse_buttons.append(intent)
        else:
            devices.append(intent)
    return tuple(keys), tuple(mouse_buttons), tuple(devices)
