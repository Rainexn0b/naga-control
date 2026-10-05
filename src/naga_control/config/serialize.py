"""Serialize immutable configuration domain values into TOML-compatible data."""

import tomli_w

from naga_control.domain.actions import (
    Action,
    DisabledAction,
    KeyAction,
    KeyComboAction,
    MouseButtonAction,
)
from naga_control.domain.profiles import (
    Binding,
    Configuration,
    LightingEffect,
    LightingZone,
    Profile,
)


def dump_toml(configuration: Configuration) -> str:
    """Serialize a complete validated configuration document."""
    return tomli_w.dumps(to_toml_data(configuration))


def to_toml_data(configuration: Configuration) -> dict[str, object]:
    """Convert a configuration to values accepted by ``tomli_w``."""
    return {
        "schema_version": configuration.schema_version,
        "revision": configuration.revision,
        "default_profile": configuration.default_profile,
        "active_profile": configuration.active_profile,
        "mode": configuration.mode,
        "profiles": {
            identifier: _profile_data(profile) for identifier, profile in configuration.profiles
        },
    }


def _profile_data(profile: Profile) -> dict[str, object]:
    return {
        "display_name": profile.display_name,
        "plate_layout": profile.plate_layout,
        "bindings": {
            "common": _bindings_data(profile.bindings.common),
            "plate_2": _bindings_data(profile.bindings.plate_2),
            "plate_6": _bindings_data(profile.bindings.plate_6),
            "plate_12": _bindings_data(profile.bindings.plate_12),
        },
        "dpi": {
            "stages": [{"x": stage.x, "y": stage.y} for stage in profile.dpi.stages],
            "active_stage": profile.dpi.active_stage,
        },
        "scroll": {
            "mode": profile.scroll.mode,
            "acceleration": profile.scroll.acceleration,
            "smart_reel": profile.scroll.smart_reel,
        },
        "lighting": {
            "thumb_grid": _zone_data(profile.lighting.thumb_grid),
            "logo": _zone_data(profile.lighting.logo),
            "scroll_wheel": _zone_data(profile.lighting.scroll_wheel),
        },
        "power": {
            "idle_seconds": profile.power.idle_seconds,
            "low_battery_threshold": profile.power.low_battery_threshold,
        },
        "poll_rate": profile.poll_rate,
    }


def _bindings_data(bindings: tuple[Binding, ...]) -> dict[str, object]:
    return {str(binding.control_id): _action_data(binding.action) for binding in bindings}


def _action_data(action: Action) -> dict[str, object]:
    if isinstance(action, DisabledAction):
        return {"type": "disabled"}
    if isinstance(action, KeyAction):
        return {"type": "key", "key": action.key}
    if isinstance(action, KeyComboAction):
        return {"type": "key_combo", "modifiers": list(action.modifiers), "key": action.key}
    if isinstance(action, MouseButtonAction):
        return {"type": "mouse_button", "button": action.button}
    return {"type": "device", "action": action.action}


def _zone_data(zone: LightingZone) -> dict[str, object]:
    return {"brightness": zone.brightness, "effect": _effect_data(zone.effect)}


def _effect_data(effect: LightingEffect) -> dict[str, object]:
    result: dict[str, object] = {"type": effect.kind}
    if effect.color is not None:
        result["color"] = list(effect.color)
    if effect.speed is not None:
        result["speed"] = effect.speed
    if effect.direction is not None:
        result["direction"] = effect.direction
    return result
