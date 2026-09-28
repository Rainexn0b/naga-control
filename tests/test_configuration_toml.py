from collections.abc import Callable
from dataclasses import FrozenInstanceError
from typing import cast

import pytest
import tomli_w

from naga_control.config import dump_toml, parse_toml, to_toml_data
from naga_control.domain import ConfigValidationError, default_configuration
from naga_control.domain.actions import DeviceAction, KeyAction, KeyComboAction, MouseButtonAction
from naga_control.domain.profiles import Configuration, Profile, as_logical_control


def test_defaults_are_complete_and_immutable() -> None:
    configuration = default_configuration()
    profile = configuration.profile("default")

    assert configuration.schema_version == 1
    assert configuration.revision == 0
    assert profile.plate_layout == 12
    assert profile.bindings.action_for("dpi_up", 12) == DeviceAction("dpi_stage_up")
    assert profile.bindings.action_for("dpi_down", 12) == DeviceAction("dpi_stage_down")
    assert profile.bindings.action_for("ring_finger", 12) == KeyAction("left_alt")
    assert profile.bindings.action_for("side_2_front", 2) == MouseButtonAction("back")
    assert profile.bindings.action_for("side_2_rear", 2) == MouseButtonAction("forward")
    assert [
        profile.bindings.action_for(as_logical_control(f"side_6_{number}"), 6)
        for number in range(1, 7)
    ] == [KeyAction(str(number)) for number in range(1, 7)]
    assert [
        profile.bindings.action_for(as_logical_control(f"side_12_{number}"), 12)
        for number in range(1, 13)
    ] == [
        KeyAction(key)
        for key in ("1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "minus", "equal")
    ]
    assert profile.dpi.active_stage == 2
    assert profile.scroll.mode == "tactile"
    assert profile.power.idle_seconds == 300
    with pytest.raises(FrozenInstanceError):
        profile.power.idle_seconds = 60  # type: ignore[misc]


def test_tomli_w_round_trip_preserves_every_v1_setting() -> None:
    data = to_toml_data(default_configuration())
    profile = _profile_data(data)
    bindings = cast(dict[str, object], profile["bindings"])
    common = cast(dict[str, object], bindings["common"])
    common["wheel_tilt_left"] = {"type": "disabled"}
    common["wheel_tilt_right"] = {
        "type": "key_combo",
        "modifiers": ["left_ctrl", "left_shift"],
        "key": "a",
    }
    common["top_front"] = {"type": "mouse_button", "button": "middle"}
    common["top_rear"] = {"type": "device", "action": "scroll_free_spin"}
    lighting = cast(dict[str, object], profile["lighting"])
    cast(dict[str, object], lighting["logo"])["effect"] = {"type": "spectrum"}
    cast(dict[str, object], lighting["scroll_wheel"])["effect"] = {
        "type": "wave",
        "direction": "right",
    }

    document = tomli_w.dumps(data)
    parsed = parse_toml(document)

    assert parse_toml(dump_toml(parsed)) == parsed
    assert parsed.profile("default").bindings.action_for("wheel_tilt_left", 12) is not None
    assert parsed.profile("default").lighting.scroll_wheel.effect.direction == "right"


def test_poll_rate_defaults_when_missing_and_round_trips_when_present() -> None:
    data = to_toml_data(default_configuration())
    profile = _profile_data(data)
    del profile["poll_rate"]

    parsed = parse_toml(tomli_w.dumps(data))
    assert parsed.profile("default").poll_rate == 1000

    profile["poll_rate"] = 125
    with_poll = parse_toml(tomli_w.dumps(data))
    assert with_poll.profile("default").poll_rate == 125
    assert parse_toml(dump_toml(with_poll)).profile("default").poll_rate == 125

    profile["poll_rate"] = 333
    with pytest.raises(ConfigValidationError, match="poll_rate"):
        parse_toml(tomli_w.dumps(data))


def _invalid_revision(data: dict[str, object]) -> None:
    data["revision"] = -1


def _invalid_dpi(data: dict[str, object]) -> None:
    _dpi_stage(data)["x"] = 99


def _invalid_power(data: dict[str, object]) -> None:
    _power(data)["low_battery_threshold"] = 26


def _invalid_rgb(data: dict[str, object]) -> None:
    _effect(data)["color"] = [0, 0, 256]


def _invalid_combo_modifier(data: dict[str, object]) -> None:
    common = cast(
        dict[str, object], cast(dict[str, object], _profile_data(data)["bindings"])["common"]
    )
    common["wheel_tilt_left"] = {"type": "key_combo", "modifiers": ["a"], "key": "b"}


INVALID_VALUE_CASES: list[tuple[Callable[[dict[str, object]], None], str]] = [
    (_invalid_revision, "revision"),
    (_invalid_dpi, "profiles.default.dpi.stages[0].x"),
    (_invalid_power, "profiles.default.power.low_battery_threshold"),
    (_invalid_rgb, "profiles.default.lighting.logo.effect.color[2]"),
    (_invalid_combo_modifier, "profiles.default.bindings.common.wheel_tilt_left.modifiers"),
]


@pytest.mark.parametrize(("mutate", "field_path"), INVALID_VALUE_CASES)
def test_invalid_values_report_their_field_path(
    mutate: Callable[[dict[str, object]], None], field_path: str
) -> None:
    data = to_toml_data(default_configuration())
    mutate(data)

    with pytest.raises(ConfigValidationError) as error:
        parse_toml(tomli_w.dumps(data))

    assert error.value.field_path == field_path


def test_malformed_toml_reports_the_document_field() -> None:
    with pytest.raises(ConfigValidationError) as error:
        parse_toml("schema_version = [")

    assert error.value.field_path == "document"


def test_unknown_nested_field_is_rejected() -> None:
    data = to_toml_data(default_configuration())
    _profile_data(data)["unexpected"] = True

    with pytest.raises(ConfigValidationError) as error:
        parse_toml(tomli_w.dumps(data))

    assert error.value.field_path == "profiles.default.unexpected"


def test_future_schema_version_is_rejected_without_migration() -> None:
    data = to_toml_data(default_configuration())
    data["schema_version"] = 2

    with pytest.raises(ConfigValidationError) as error:
        parse_toml(tomli_w.dumps(data))

    assert error.value.field_path == "schema_version"


def test_empty_dpi_stages_reports_the_stage_field() -> None:
    data = to_toml_data(default_configuration())
    dpi = cast(dict[str, object], _profile_data(data)["dpi"])
    dpi["stages"] = []

    with pytest.raises(ConfigValidationError) as error:
        parse_toml(tomli_w.dumps(data))

    assert error.value.field_path == "profiles.default.dpi.stages"


def test_thumb_grid_wave_is_rejected() -> None:
    data = to_toml_data(default_configuration())
    lighting = cast(dict[str, object], _profile_data(data)["lighting"])
    cast(dict[str, object], lighting["thumb_grid"])["effect"] = {
        "type": "wave",
        "direction": "left",
    }

    with pytest.raises(ConfigValidationError) as error:
        parse_toml(tomli_w.dumps(data))

    assert error.value.field_path == "profiles.default.lighting.thumb_grid.effect"


def test_configuration_copies_mutable_constructor_inputs() -> None:
    configuration = default_configuration()
    profiles = [*configuration.profiles]
    modifiers = ["left_ctrl"]
    action = KeyComboAction(cast(tuple[str, ...], modifiers), "a")
    copied = Configuration(
        revision=configuration.revision,
        default_profile=configuration.default_profile,
        active_profile=configuration.active_profile,
        profiles=cast(tuple[tuple[str, Profile], ...], profiles),
    )

    profiles.clear()
    modifiers.append("left_shift")

    assert copied.profiles == configuration.profiles
    assert action.modifiers == ("left_ctrl",)


def _profile_data(data: dict[str, object]) -> dict[str, object]:
    profiles = cast(dict[str, object], data["profiles"])
    return cast(dict[str, object], profiles["default"])


def _dpi_stage(data: dict[str, object]) -> dict[str, object]:
    dpi = cast(dict[str, object], _profile_data(data)["dpi"])
    stages = cast(list[object], dpi["stages"])
    return cast(dict[str, object], stages[0])


def _power(data: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], _profile_data(data)["power"])


def _effect(data: dict[str, object]) -> dict[str, object]:
    lighting = cast(dict[str, object], _profile_data(data)["lighting"])
    logo = cast(dict[str, object], lighting["logo"])
    return cast(dict[str, object], logo["effect"])
