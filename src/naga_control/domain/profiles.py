"""Immutable desired configuration types for Naga profiles."""

import re
from dataclasses import dataclass
from typing import Literal, cast

from naga_control.domain.actions import Action
from naga_control.domain.errors import ConfigValidationError
from naga_control.domain.hardware import DeviceMode

type PlateLayout = Literal[2, 6, 12]
type ScrollMode = Literal["tactile", "free_spin", "precision_tactile"]
type CommonControlId = Literal[
    "dpi_up",
    "dpi_down",
    "wheel_tilt_left",
    "wheel_tilt_right",
    "ring_finger",
    "top_front",
    "top_rear",
]
type PlateControlId = Literal[
    "side_2_front",
    "side_2_rear",
    "side_6_1",
    "side_6_2",
    "side_6_3",
    "side_6_4",
    "side_6_5",
    "side_6_6",
    "side_12_1",
    "side_12_2",
    "side_12_3",
    "side_12_4",
    "side_12_5",
    "side_12_6",
    "side_12_7",
    "side_12_8",
    "side_12_9",
    "side_12_10",
    "side_12_11",
    "side_12_12",
]
type LogicalControlId = CommonControlId | PlateControlId

COMMON_CONTROL_IDS = frozenset(
    {
        "dpi_up",
        "dpi_down",
        "wheel_tilt_left",
        "wheel_tilt_right",
        "ring_finger",
        "top_front",
        "top_rear",
    }
)
PLATE_CONTROL_IDS: dict[PlateLayout, frozenset[str]] = {
    2: frozenset({"side_2_front", "side_2_rear"}),
    6: frozenset(f"side_6_{number}" for number in range(1, 7)),
    12: frozenset(f"side_12_{number}" for number in range(1, 13)),
}
PROFILE_ID_RE = re.compile(r"[a-z][a-z0-9-]*\Z")


@dataclass(frozen=True, slots=True)
class Binding:
    control_id: LogicalControlId
    action: Action


@dataclass(frozen=True, slots=True)
class Bindings:
    common: tuple[Binding, ...]
    plate_2: tuple[Binding, ...]
    plate_6: tuple[Binding, ...]
    plate_12: tuple[Binding, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "common", tuple(self.common))
        object.__setattr__(self, "plate_2", tuple(self.plate_2))
        object.__setattr__(self, "plate_6", tuple(self.plate_6))
        object.__setattr__(self, "plate_12", tuple(self.plate_12))
        _validate_bindings(self.common, COMMON_CONTROL_IDS, "bindings.common")
        _validate_bindings(self.plate_2, PLATE_CONTROL_IDS[2], "bindings.plate_2")
        _validate_bindings(self.plate_6, PLATE_CONTROL_IDS[6], "bindings.plate_6")
        _validate_bindings(self.plate_12, PLATE_CONTROL_IDS[12], "bindings.plate_12")

    def action_for(self, control_id: LogicalControlId, plate_layout: PlateLayout) -> Action | None:
        for binding in self.common + _plate_bindings(self, plate_layout):
            if binding.control_id == control_id:
                return binding.action
        return None


@dataclass(frozen=True, slots=True)
class DpiStage:
    x: int
    y: int

    def __post_init__(self) -> None:
        _validate_range(self.x, "x", 100, 50000)
        _validate_range(self.y, "y", 100, 50000)


@dataclass(frozen=True, slots=True)
class DpiSettings:
    stages: tuple[DpiStage, ...]
    active_stage: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "stages", tuple(self.stages))
        if not 1 <= len(self.stages) <= 5:
            raise ConfigValidationError("stages", "must contain from 1 through 5 stages")
        _validate_range(self.active_stage, "active_stage", 1, len(self.stages))


@dataclass(frozen=True, slots=True)
class ScrollSettings:
    mode: ScrollMode
    acceleration: bool
    smart_reel: bool

    def __post_init__(self) -> None:
        if self.mode not in {"tactile", "free_spin", "precision_tactile"}:
            raise ConfigValidationError("mode", "must be tactile, free_spin, or precision_tactile")
        _validate_bool(self.acceleration, "acceleration")
        _validate_bool(self.smart_reel, "smart_reel")


type RgbColor = tuple[int, int, int]
type LightingEffectKind = Literal["off", "static", "spectrum", "breathing", "reactive", "wave"]


@dataclass(frozen=True, slots=True)
class LightingEffect:
    kind: LightingEffectKind
    color: RgbColor | None = None
    speed: int | None = None
    direction: Literal["left", "right"] | None = None

    def __post_init__(self) -> None:
        if self.color is not None:
            object.__setattr__(self, "color", tuple(self.color))
        valid = {"off", "static", "spectrum", "breathing", "reactive", "wave"}
        if self.kind not in valid:
            raise ConfigValidationError("kind", "must be a supported lighting effect")
        if self.kind in {"static", "breathing"}:
            _require_effect_fields(self, color=True)
        elif self.kind == "reactive":
            _require_effect_fields(self, color=True, speed=True)
        elif self.kind == "wave":
            _require_effect_fields(self, direction=True)
        elif self.color is not None or self.speed is not None or self.direction is not None:
            raise ConfigValidationError("effect", "does not accept payload fields")
        if self.color is not None:
            _validate_rgb(self.color)
        if self.speed is not None:
            _validate_range(self.speed, "speed", 1, 4)
        if self.direction is not None and self.direction not in {"left", "right"}:
            raise ConfigValidationError("direction", "must be left or right")


@dataclass(frozen=True, slots=True)
class LightingZone:
    brightness: int
    effect: LightingEffect

    def __post_init__(self) -> None:
        _validate_range(self.brightness, "brightness", 0, 100)


@dataclass(frozen=True, slots=True)
class LightingSettings:
    thumb_grid: LightingZone
    logo: LightingZone
    scroll_wheel: LightingZone

    def __post_init__(self) -> None:
        if self.thumb_grid.effect.kind == "wave":
            raise ConfigValidationError("thumb_grid.effect", "does not support wave")


@dataclass(frozen=True, slots=True)
class PowerSettings:
    idle_seconds: int
    low_battery_threshold: int

    def __post_init__(self) -> None:
        _validate_range(self.idle_seconds, "idle_seconds", 60, 900)
        _validate_range(self.low_battery_threshold, "low_battery_threshold", 0, 25)


@dataclass(frozen=True, slots=True)
class Profile:
    display_name: str
    plate_layout: PlateLayout
    bindings: Bindings
    dpi: DpiSettings
    scroll: ScrollSettings
    lighting: LightingSettings
    power: PowerSettings
    poll_rate: int = 1000

    def __post_init__(self) -> None:
        if type(self.display_name) is not str or not self.display_name.strip():
            raise ConfigValidationError("display_name", "must be a non-empty string")
        if self.plate_layout not in {2, 6, 12}:
            raise ConfigValidationError("plate_layout", "must be 2, 6, or 12")
        if self.poll_rate not in {125, 500, 1000}:
            raise ConfigValidationError("poll_rate", "must be 125, 500, or 1000")


@dataclass(frozen=True, slots=True)
class Configuration:
    revision: int
    default_profile: str
    active_profile: str
    profiles: tuple[tuple[str, Profile], ...]
    schema_version: Literal[1] = 1
    mode: DeviceMode = "software"

    def __post_init__(self) -> None:
        object.__setattr__(self, "profiles", tuple(self.profiles))
        if self.schema_version != 1:
            raise ConfigValidationError("schema_version", "must be 1")
        if type(self.mode) is not str or self.mode not in {"software", "firmware"}:
            raise ConfigValidationError("mode", "must be software or firmware")
        _validate_range(self.revision, "revision", 0, 2**63 - 1)
        if not self.profiles:
            raise ConfigValidationError("profiles", "must contain at least one profile")
        identifiers = tuple(identifier for identifier, _ in self.profiles)
        for identifier in identifiers:
            if type(identifier) is not str or not PROFILE_ID_RE.fullmatch(identifier):
                raise ConfigValidationError("profiles", "profile IDs must be lowercase ASCII slugs")
        if len(set(identifiers)) != len(identifiers):
            raise ConfigValidationError("profiles", "profile IDs must be unique")
        if self.default_profile not in identifiers:
            raise ConfigValidationError("default_profile", "must reference an existing profile")
        if self.active_profile not in identifiers:
            raise ConfigValidationError("active_profile", "must reference an existing profile")

    def profile(self, identifier: str) -> Profile:
        for profile_id, profile in self.profiles:
            if profile_id == identifier:
                return profile
        raise KeyError(identifier)


def _plate_bindings(bindings: Bindings, layout: PlateLayout) -> tuple[Binding, ...]:
    return {2: bindings.plate_2, 6: bindings.plate_6, 12: bindings.plate_12}[layout]


def _validate_bindings(
    bindings: tuple[Binding, ...], allowed_controls: frozenset[str], field_path: str
) -> None:
    controls = tuple(binding.control_id for binding in bindings)
    if len(set(controls)) != len(controls):
        raise ConfigValidationError(field_path, "must not contain duplicate control IDs")
    for control in controls:
        if control not in allowed_controls:
            raise ConfigValidationError(field_path, f"contains invalid control ID {control!r}")


def _validate_range(value: int, field_path: str, minimum: int, maximum: int) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ConfigValidationError(
            field_path, f"must be an integer from {minimum} through {maximum}"
        )


def _validate_bool(value: bool, field_path: str) -> None:
    if type(value) is not bool:
        raise ConfigValidationError(field_path, "must be a boolean")


def _validate_rgb(color: RgbColor) -> None:
    if len(color) != 3:
        raise ConfigValidationError("color", "must have exactly three RGB components")
    for value in color:
        _validate_range(value, "color", 0, 255)


def _require_effect_fields(
    effect: LightingEffect,
    *,
    color: bool = False,
    speed: bool = False,
    direction: bool = False,
) -> None:
    if (
        (color and effect.color is None)
        or (speed and effect.speed is None)
        or (direction and effect.direction is None)
    ):
        raise ConfigValidationError("effect", "is missing a required payload field")
    if (
        (not color and effect.color is not None)
        or (not speed and effect.speed is not None)
        or (not direction and effect.direction is not None)
    ):
        raise ConfigValidationError("effect", "has an unsupported payload field")


def as_logical_control(value: str) -> LogicalControlId:
    """Narrow a checked control ID for typed construction at parser boundaries."""
    return cast(LogicalControlId, value)
