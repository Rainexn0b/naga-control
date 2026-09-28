"""Qt-free view helpers for the scroll, lighting, and power pages."""

from naga_control.domain.errors import ConfigValidationError
from naga_control.domain.profiles import LightingEffect, Profile, ScrollMode

SCROLL_MODES: tuple[ScrollMode, ...] = ("tactile", "free_spin", "precision_tactile")

LIGHTING_KINDS = ("off", "static", "spectrum", "breathing", "reactive", "wave")
LIGHTING_SPEEDS = (1, 2, 3, 4)
LIGHTING_DIRECTIONS = ("left", "right")
ZONES = ("thumb_grid", "logo", "scroll_wheel")
ZONE_LABELS = {
    "thumb_grid": "Thumb grid",
    "logo": "Logo",
    "scroll_wheel": "Scroll wheel",
}


def effect_payloads(kind: str) -> tuple[bool, bool, bool]:
    """Return (wants_color, wants_speed, wants_direction) for an effect kind."""
    if kind in {"static", "breathing"}:
        return (True, False, False)
    if kind == "reactive":
        return (True, True, False)
    if kind == "wave":
        return (False, False, True)
    return (False, False, False)


def scroll_values(profile: Profile) -> tuple[ScrollMode, bool, bool]:
    return (profile.scroll.mode, profile.scroll.acceleration, profile.scroll.smart_reel)


def power_values(profile: Profile) -> tuple[int, int]:
    return (profile.power.idle_seconds, profile.power.low_battery_threshold)


def zone_values(profile: Profile, zone: str) -> tuple[int, LightingEffect]:
    lighting_zone = getattr(profile.lighting, zone)
    return (lighting_zone.brightness, lighting_zone.effect)


def zone_effect_allowed(zone: str, kind: str) -> bool:
    return not (zone == "thumb_grid" and kind == "wave")


def format_color(color: tuple[int, int, int] | None) -> str:
    return "255,255,255" if color is None else ",".join(str(part) for part in color)


def parse_color(text: str) -> tuple[int, int, int]:
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 3:
        raise ConfigValidationError("color", "must be three comma-separated numbers")
    try:
        values = tuple(int(part) for part in parts)
    except ValueError as exc:
        raise ConfigValidationError("color", "must be integers") from exc
    if any(not 0 <= value <= 255 for value in values):
        raise ConfigValidationError("color", "components must be within 0 through 255")
    return values  # pyright: ignore[reportReturnType]


def effect_from_parts(
    kind: str,
    color: tuple[int, int, int] | None,
    speed: int | None,
    direction: str | None,
) -> LightingEffect:
    wants_color, wants_speed, wants_direction = effect_payloads(kind)
    return LightingEffect(
        kind=kind,  # pyright: ignore[reportArgumentType]
        color=color if wants_color else None,
        speed=speed if wants_speed else None,
        direction=direction if wants_direction else None,  # pyright: ignore[reportArgumentType]
    )
