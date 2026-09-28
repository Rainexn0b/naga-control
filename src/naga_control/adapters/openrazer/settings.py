"""Ordered application of desired profile settings to an OpenRazer client."""

import logging
from collections.abc import Callable
from typing import Protocol, cast

from naga_control.adapters.openrazer.capabilities import SCROLL_MODES
from naga_control.domain.hardware import SettingsFailure
from naga_control.domain.profiles import LightingEffect, LightingZone, Profile, RgbColor

logger = logging.getLogger(__name__)

type _Step = tuple[str, Callable[[], None]]

_WAVE_DIRECTIONS = {"left": 1, "right": 2}


class _MutableSettingsClient(Protocol):
    dpi_stages: object
    scroll_mode: object
    scroll_acceleration: object
    scroll_smart_reel: object
    poll_rate: int

    def set_idle_time(self, seconds: int) -> None: ...

    def set_low_battery_threshold(self, percent: int) -> None: ...


def apply_steps(client: object, profile: Profile) -> tuple[SettingsFailure, ...]:
    """Run every settings write in order and collect per-step failures."""
    mutable = cast(_MutableSettingsClient, client)
    steps: tuple[_Step, ...] = (
        ("dpi_stages", lambda: setattr(mutable, "dpi_stages", _stage_write(profile))),
        (
            "scroll_mode",
            lambda: setattr(mutable, "scroll_mode", SCROLL_MODES.index(profile.scroll.mode)),
        ),
        (
            "scroll_acceleration",
            lambda: setattr(mutable, "scroll_acceleration", profile.scroll.acceleration),
        ),
        (
            "scroll_smart_reel",
            lambda: setattr(mutable, "scroll_smart_reel", profile.scroll.smart_reel),
        ),
        ("idle_seconds", lambda: mutable.set_idle_time(profile.power.idle_seconds)),
        (
            "low_battery_threshold",
            lambda: mutable.set_low_battery_threshold(profile.power.low_battery_threshold),
        ),
        ("poll_rate", lambda: setattr(mutable, "poll_rate", profile.poll_rate)),
        ("lighting_thumb_grid", lambda: _apply_matrix(client, profile.lighting.thumb_grid)),
        ("lighting_logo", lambda: _apply_misc(client, "logo", profile.lighting.logo)),
        (
            "lighting_scroll_wheel",
            lambda: _apply_misc(client, "scroll_wheel", profile.lighting.scroll_wheel),
        ),
    )
    failures: list[SettingsFailure] = []
    for setting, write in steps:
        try:
            write()
        except Exception as exc:
            failures.append(SettingsFailure(setting, str(exc) or exc.__class__.__name__))
            logger.warning("setting %s could not be applied: %s", setting, exc)
    return tuple(failures)


class _FxZone(Protocol):
    brightness: float

    def none(self) -> object: ...

    def static(self, red: int, green: int, blue: int) -> object: ...

    def spectrum(self) -> object: ...

    def breath_single(self, red: int, green: int, blue: int) -> object: ...

    def reactive(self, red: int, green: int, blue: int, speed: int) -> object: ...

    def wave(self, direction: int) -> object: ...


class _FxMisc(Protocol):
    logo: object
    scroll_wheel: object


class _FxRoot(Protocol):
    misc: _FxMisc


class _BrightnessClient(Protocol):
    brightness: float
    fx: _FxRoot


def _apply_matrix(client: object, zone: LightingZone) -> None:
    holder = cast("_BrightnessClient", client)
    holder.brightness = zone.brightness
    _apply_effect(cast("_FxZone", holder.fx), zone.effect)


def _apply_misc(client: object, attribute: str, zone: LightingZone) -> None:
    target = cast("_FxZone", getattr(cast("_BrightnessClient", client).fx.misc, attribute))
    target.brightness = zone.brightness
    _apply_effect(target, zone.effect)


def _apply_effect(target: _FxZone, effect: LightingEffect) -> None:
    if effect.kind == "off":
        target.none()
    elif effect.kind == "static":
        target.static(*_color(effect))
    elif effect.kind == "spectrum":
        target.spectrum()
    elif effect.kind == "breathing":
        target.breath_single(*_color(effect))
    elif effect.kind == "reactive":
        target.reactive(*_color(effect), effect.speed or 1)
    else:
        target.wave(_WAVE_DIRECTIONS[effect.direction or "left"])


def _color(effect: LightingEffect) -> RgbColor:
    return cast("RgbColor", effect.color)


def _stage_write(profile: Profile) -> tuple[int, tuple[tuple[int, int], ...]]:
    return (
        profile.dpi.active_stage,
        tuple((stage.x, stage.y) for stage in profile.dpi.stages),
    )
