import pytest

from naga_control.domain.defaults import default_configuration
from naga_control.domain.errors import ConfigValidationError
from naga_control.domain.profiles import LightingEffect
from naga_control.gui.settings_view import (
    effect_from_parts,
    effect_payloads,
    format_color,
    parse_color,
    zone_effect_allowed,
)


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("off", (False, False, False)),
        ("static", (True, False, False)),
        ("spectrum", (False, False, False)),
        ("breathing", (True, False, False)),
        ("reactive", (True, True, False)),
        ("wave", (False, False, True)),
    ],
)
def test_effect_payloads_match_domain_requirements(
    kind: str, expected: tuple[bool, bool, bool]
) -> None:
    assert effect_payloads(kind) == expected


def test_effect_from_parts_ignores_unwanted_payloads() -> None:
    effect = effect_from_parts("spectrum", (255, 0, 0), 3, "left")

    assert effect == LightingEffect(kind="spectrum")


def test_effect_from_parts_keeps_wanted_payloads() -> None:
    effect = effect_from_parts("reactive", (10, 20, 30), 2, "right")

    assert effect == LightingEffect(kind="reactive", color=(10, 20, 30), speed=2)


def test_color_formatting_and_parsing_round_trip() -> None:
    assert format_color((10, 20, 30)) == "10,20,30"
    assert parse_color("10, 20, 30") == (10, 20, 30)
    assert parse_color(format_color(None)) == (255, 255, 255)


def test_parse_color_rejects_bad_input() -> None:
    with pytest.raises(ConfigValidationError):
        parse_color("red")
    with pytest.raises(ConfigValidationError):
        parse_color("1,2")
    with pytest.raises(ConfigValidationError):
        parse_color("1,2,300")


def test_thumb_grid_forbids_wave_only() -> None:
    assert zone_effect_allowed("thumb_grid", "wave") is False
    assert zone_effect_allowed("logo", "wave") is True
    assert zone_effect_allowed("scroll_wheel", "static") is True


def test_zone_and_power_helpers_read_the_domain() -> None:
    from naga_control.gui.settings_view import power_values, scroll_values, zone_values

    profile = default_configuration().profile(default_configuration().active_profile)
    assert scroll_values(profile) == (
        profile.scroll.mode,
        profile.scroll.acceleration,
        profile.scroll.smart_reel,
    )
    assert power_values(profile) == (
        profile.power.idle_seconds,
        profile.power.low_battery_threshold,
    )
    assert zone_values(profile, "logo") == (
        profile.lighting.logo.brightness,
        profile.lighting.logo.effect,
    )
