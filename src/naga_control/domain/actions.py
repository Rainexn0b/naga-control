"""Immutable action variants for logical button bindings."""

from dataclasses import dataclass, field
from typing import Literal

from naga_control.domain.errors import ConfigValidationError

type DeviceActionToken = Literal[
    "dpi_stage_up",
    "dpi_stage_down",
    "scroll_mode_next",
    "scroll_mode_previous",
    "scroll_tactile",
    "scroll_precision_tactile",
    "scroll_free_spin",
]

DEVICE_ACTIONS = frozenset(
    {
        "dpi_stage_up",
        "dpi_stage_down",
        "scroll_mode_next",
        "scroll_mode_previous",
        "scroll_tactile",
        "scroll_precision_tactile",
        "scroll_free_spin",
    }
)
MOUSE_BUTTONS = frozenset({"left", "right", "middle", "back", "forward"})
MODIFIER_KEYS = frozenset(
    {
        "left_alt",
        "right_alt",
        "left_ctrl",
        "right_ctrl",
        "left_shift",
        "right_shift",
        "left_super",
        "right_super",
    }
)
OUTPUT_KEY_TOKENS: frozenset[str] = MODIFIER_KEYS | frozenset(
    {
        *(str(digit) for digit in range(1, 10)),
        "0",
        "minus",
        "equal",
        "left_brace",
        "right_brace",
        *(chr(letter) for letter in range(ord("a"), ord("z") + 1)),
        "space",
        "tab",
        "backspace",
        "enter",
        "escape",
        "delete",
        "insert",
        "up",
        "down",
        "left",
        "right",
        "home",
        "end",
        "page_up",
        "page_down",
        *(f"f{number}" for number in range(1, 13)),
    }
)


@dataclass(frozen=True, slots=True)
class DisabledAction:
    kind: Literal["disabled"] = field(default="disabled", init=False)


@dataclass(frozen=True, slots=True)
class KeyAction:
    key: str
    kind: Literal["key"] = field(default="key", init=False)

    def __post_init__(self) -> None:
        _validate_output_token(self.key, "key")


@dataclass(frozen=True, slots=True)
class KeyComboAction:
    modifiers: tuple[str, ...]
    key: str
    kind: Literal["key_combo"] = field(default="key_combo", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "modifiers", tuple(self.modifiers))
        if not self.modifiers:
            raise ConfigValidationError("modifiers", "must contain at least one key token")
        if len(set(self.modifiers)) != len(self.modifiers):
            raise ConfigValidationError("modifiers", "must not contain duplicate key tokens")
        for modifier in self.modifiers:
            _validate_token(modifier, "modifiers")
            if modifier not in MODIFIER_KEYS:
                raise ConfigValidationError("modifiers", "must contain only modifier key tokens")
        _validate_output_token(self.key, "key")


@dataclass(frozen=True, slots=True)
class MouseButtonAction:
    button: str
    kind: Literal["mouse_button"] = field(default="mouse_button", init=False)

    def __post_init__(self) -> None:
        if self.button not in MOUSE_BUTTONS:
            raise ConfigValidationError("button", "must be a supported mouse button token")


@dataclass(frozen=True, slots=True)
class DeviceAction:
    action: DeviceActionToken
    kind: Literal["device"] = field(default="device", init=False)

    def __post_init__(self) -> None:
        if self.action not in DEVICE_ACTIONS:
            raise ConfigValidationError("action", "must be a supported device action token")


type Action = DisabledAction | KeyAction | KeyComboAction | MouseButtonAction | DeviceAction


def _validate_token(value: str, field_path: str) -> None:
    if type(value) is not str or not value:
        raise ConfigValidationError(field_path, "must be a non-empty key token")
    if not value.isascii() or any(
        not (char.islower() or char.isdigit() or char == "_") for char in value
    ):
        raise ConfigValidationError(field_path, "must use lowercase ASCII key-token syntax")
    if value.startswith(("key_", "btn_")):
        raise ConfigValidationError(field_path, "must not use a Linux KEY_ or BTN_ name")


def _validate_output_token(value: str, field_path: str) -> None:
    _validate_token(value, field_path)
    if value not in OUTPUT_KEY_TOKENS:
        raise ConfigValidationError(field_path, f"unsupported key token {value!r}")
