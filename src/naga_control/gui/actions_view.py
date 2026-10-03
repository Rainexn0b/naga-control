"""Qt-free formatting and parsing for action bindings shown in the GUI."""

from typing import cast

from naga_control.domain.actions import (
    DEVICE_ACTIONS,
    MODIFIER_KEYS,
    MOUSE_BUTTONS,
    Action,
    DeviceAction,
    DeviceActionToken,
    DisabledAction,
    KeyAction,
    KeyComboAction,
    MouseButtonAction,
)
from naga_control.domain.errors import ConfigValidationError
from naga_control.domain.profiles import Binding, Bindings, LogicalControlId

ACTION_KINDS = ("passthrough", "disabled", "key", "key_combo", "mouse_button", "device")

_CONTROL_LABELS: dict[str, str] = {
    "dpi_up": "DPI up",
    "dpi_down": "DPI down",
    "wheel_tilt_left": "Wheel tilt left",
    "wheel_tilt_right": "Wheel tilt right",
    "ring_finger": "Ring finger",
    "top_front": "Top front",
    "top_rear": "Top rear",
    "side_2_front": "Side front",
    "side_2_rear": "Side rear",
}


def control_display_name(control_id: str) -> str:
    label = _CONTROL_LABELS.get(control_id)
    if label is not None:
        return label
    if control_id.startswith("side_"):
        parts = control_id.split("_")
        if len(parts) == 3 and parts[2].isdigit():
            plate = parts[1]
            return f"Side {parts[2]} ({plate}-button plate)"
    return control_id


def action_kind(action: Action) -> str:
    if isinstance(action, DisabledAction):
        return "disabled"
    if isinstance(action, KeyAction):
        return "key"
    if isinstance(action, KeyComboAction):
        return "key_combo"
    if isinstance(action, MouseButtonAction):
        return "mouse_button"
    return "device"


def format_action_detail(action: Action) -> str:
    if isinstance(action, DisabledAction):
        return ""
    if isinstance(action, KeyAction):
        return action.key
    if isinstance(action, KeyComboAction):
        return "+".join([*action.modifiers, action.key])
    if isinstance(action, MouseButtonAction):
        return action.button
    return action.action


def parse_action(kind: str, detail: str) -> Action:
    """Build an action from editor widgets, validating through the domain."""
    text = detail.strip()
    if kind == "disabled":
        return DisabledAction()
    if kind == "key":
        _require(text, "key")
        return KeyAction(key=text)
    if kind == "key_combo":
        _require(text, "key combo")
        tokens = [token.strip() for token in text.split("+")]
        if len(tokens) < 2:
            raise ConfigValidationError("key_combo", "must be modifiers plus a key")
        unknown = [token for token in tokens[:-1] if token not in MODIFIER_KEYS]
        if unknown:
            raise ConfigValidationError(
                "key_combo", f"unsupported modifier tokens: {', '.join(unknown)}"
            )
        return KeyComboAction(modifiers=tuple(tokens[:-1]), key=tokens[-1])
    if kind == "mouse_button":
        if text not in MOUSE_BUTTONS:
            raise ConfigValidationError(
                "mouse_button", f"must be one of: {', '.join(sorted(MOUSE_BUTTONS))}"
            )
        return MouseButtonAction(button=text)
    if kind == "device":
        if text not in DEVICE_ACTIONS:
            raise ConfigValidationError(
                "device", f"must be one of: {', '.join(sorted(DEVICE_ACTIONS))}"
            )
        return DeviceAction(action=cast(DeviceActionToken, text))
    raise ConfigValidationError("action", f"unsupported action kind {kind!r}")


def is_control_id(value: str) -> bool:
    from naga_control.domain.profiles import COMMON_CONTROL_IDS, PLATE_CONTROL_IDS

    return (
        value in COMMON_CONTROL_IDS
        or value in PLATE_CONTROL_IDS[2]
        or value in PLATE_CONTROL_IDS[6]
        or value in PLATE_CONTROL_IDS[12]
    )


def _require(text: str, field_path: str) -> None:
    if not text:
        raise ConfigValidationError(field_path, "must not be empty")


def _control_sort_key(control_id: str) -> tuple[str, int, str]:
    parts = control_id.rpartition("_")
    number = int(parts[2]) if parts[2].isdigit() else 0
    return (parts[0], number, parts[2])


def _numeric_sorted(control_ids: frozenset[str]) -> tuple[str, ...]:
    return tuple(sorted(control_ids, key=_control_sort_key))


def controls_for_layout(plate_layout: int) -> tuple[LogicalControlId, ...]:
    from typing import cast

    from naga_control.domain.profiles import COMMON_CONTROL_IDS, PLATE_CONTROL_IDS, PlateLayout

    common = _numeric_sorted(COMMON_CONTROL_IDS)
    plate = _numeric_sorted(PLATE_CONTROL_IDS[cast(PlateLayout, plate_layout)])
    return cast("tuple[LogicalControlId, ...]", (*common, *plate))


def control_groups() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Every control grouped by plate, numerically ordered."""
    from naga_control.domain.profiles import COMMON_CONTROL_IDS, PLATE_CONTROL_IDS

    return (
        ("Common controls", _numeric_sorted(COMMON_CONTROL_IDS)),
        ("12-button plate", _numeric_sorted(PLATE_CONTROL_IDS[12])),
        ("6-button plate", _numeric_sorted(PLATE_CONTROL_IDS[6])),
        ("2-button plate", _numeric_sorted(PLATE_CONTROL_IDS[2])),
    )


def action_for_control(bindings: Bindings, control_id: str) -> Action | None:
    """Read a binding from its own plate group, whatever plate is attached."""
    groups: dict[str, tuple[Binding, ...]] = {
        "side_12": bindings.plate_12,
        "side_6": bindings.plate_6,
        "side_2": bindings.plate_2,
    }
    prefix = "_".join(control_id.split("_")[:2])
    search: tuple[Binding, ...] = groups.get(prefix, bindings.common)
    for binding in search:
        if binding.control_id == control_id:
            return binding.action
    return None
