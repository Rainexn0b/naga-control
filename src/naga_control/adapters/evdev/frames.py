"""Translate ordered evdev frames using fixture-backed physical signatures."""

from collections.abc import Mapping
from dataclasses import dataclass

from naga_control.adapters.evdev.discovery import EventNode
from naga_control.domain.profiles import LogicalControlId

EV_SYN = 0
EV_KEY = 1
EV_MSC = 4
SYN_REPORT = 0
SYN_DROPPED = 3
MSC_SCAN = 4


@dataclass(frozen=True, slots=True)
class RawInputEvent:
    """A single input event without an evdev dependency at the parser boundary."""

    event_type: int
    code: int
    value: int


@dataclass(frozen=True, slots=True)
class RawControlSignature:
    """Stable physical control identity, populated only from sanitized captures."""

    product_id: str
    interface_number: str
    event_type: int
    event_code: int
    scan_code: int | None


@dataclass(frozen=True, slots=True)
class LogicalControlEvent:
    control_id: LogicalControlId
    value: int
    key_event_index: int = -1
    scan_event_index: int | None = None


@dataclass(frozen=True, slots=True)
class ParsedFrame:
    """A complete source frame and the logical control transitions within it."""

    events: tuple[RawInputEvent, ...]
    controls: tuple[LogicalControlEvent, ...]
    reset_controls: tuple[LogicalControlId, ...] = ()
    resync_required: bool = False
    active_key_codes: tuple[int, ...] = ()
    active_abs_values: tuple[tuple[int, int], ...] = ()


class FrameParser:
    """Buffer complete frames and retain control identity from press through release."""

    def __init__(
        self,
        node: EventNode,
        translations: Mapping[RawControlSignature, LogicalControlId],
    ) -> None:
        self._node = node
        self._translations = dict(translations)
        self._frame: list[RawInputEvent] = []
        self._controls: list[LogicalControlEvent] = []
        self._pending_scan: tuple[int, int] | None = None
        self._pressed: dict[int, LogicalControlId] = {}
        self._discarding = False

    def push(self, event: RawInputEvent) -> ParsedFrame | None:
        """Accept one raw event and return a result only at a frame boundary."""
        if event.event_type == EV_SYN and event.code == SYN_DROPPED:
            self._frame.clear()
            self._controls.clear()
            self._pending_scan = None
            self._discarding = True
            return None

        if self._discarding:
            if event.event_type == EV_SYN and event.code == SYN_REPORT:
                self._discarding = False
                reset_controls = tuple(self._pressed.values())
                self._pressed.clear()
                return ParsedFrame((), (), reset_controls, resync_required=True)
            return None

        self._frame.append(event)
        if event.event_type == EV_MSC and event.code == MSC_SCAN:
            self._pending_scan = (len(self._frame) - 1, event.value)
        elif event.event_type == EV_KEY:
            self._handle_key(event)

        if event.event_type != EV_SYN or event.code != SYN_REPORT:
            return None

        result = ParsedFrame(tuple(self._frame), tuple(self._controls))
        self._frame.clear()
        self._controls = []
        self._pending_scan = None
        return result

    def reset(self) -> tuple[LogicalControlId, ...]:
        """Discard incomplete input and return controls needing a logical release."""
        reset_controls = tuple(self._pressed.values())
        self._frame.clear()
        self._controls.clear()
        self._pending_scan = None
        self._pressed.clear()
        self._discarding = False
        return reset_controls

    def _handle_key(self, event: RawInputEvent) -> None:
        key_event_index = len(self._frame) - 1
        scan_event_index = self._pending_scan[0] if self._pending_scan is not None else None
        control_id = self._pressed.get(event.code)
        if event.value == 1:
            if control_id is not None:
                self._pending_scan = None
                return
            control_id = self._translations.get(
                RawControlSignature(
                    product_id=self._node.product_id,
                    interface_number=self._node.interface_number,
                    event_type=event.event_type,
                    event_code=event.code,
                    scan_code=self._pending_scan[1] if self._pending_scan is not None else None,
                )
            )
            if control_id is not None:
                self._pressed[event.code] = control_id
        elif event.value == 0:
            control_id = self._pressed.pop(event.code, None)

        if control_id is not None:
            self._controls.append(
                LogicalControlEvent(control_id, event.value, key_event_index, scan_event_index)
            )
        self._pending_scan = None
