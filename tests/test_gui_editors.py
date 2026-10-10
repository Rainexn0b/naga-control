from dataclasses import replace
from typing import cast

import pytest

from naga_control.config import dump_toml, parse_toml
from naga_control.domain.actions import Action, DeviceAction, KeyAction, MouseButtonAction
from naga_control.domain.defaults import default_configuration
from naga_control.domain.errors import ConfigValidationError
from naga_control.domain.profiles import (
    LightingEffect,
    LightingSettings,
    LightingZone,
    LogicalControlId,
    Profile,
)
from naga_control.gui.editors import (
    duplicate_profile,
    edit_profile,
    remove_profile,
    rename_profile,
    set_bindings,
    set_dpi_stages,
    set_lighting,
    set_power,
    set_scroll,
)


def _document() -> str:
    return dump_toml(default_configuration())


def test_set_dpi_stages_replaces_stages_and_bumps_revision() -> None:
    document = _document()
    profile_id = parse_toml(document).active_profile

    updated = set_dpi_stages(document, profile_id, [(400, 400), (800, 800), (6400, 6400)], 2)

    configuration = parse_toml(updated)
    assert configuration.revision == parse_toml(document).revision + 1
    stages = configuration.profile(profile_id).dpi.stages
    assert [(stage.x, stage.y) for stage in stages] == [(400, 400), (800, 800), (6400, 6400)]
    assert configuration.profile(profile_id).dpi.active_stage == 2


def test_set_dpi_stages_leaves_other_profiles_untouched() -> None:
    base = default_configuration()
    second = replace(base, profiles=(*base.profiles, ("mmo", base.profile(base.default_profile))))
    document = dump_toml(second)

    updated = set_dpi_stages(document, base.active_profile, [(1234, 1234)], 1)

    configuration = parse_toml(updated)
    untouched = configuration.profile("mmo").dpi.stages
    original = base.profile(base.default_profile).dpi.stages
    assert [(s.x, s.y) for s in untouched] == [(s.x, s.y) for s in original]


def test_set_dpi_stages_rejects_invalid_values_through_the_domain() -> None:
    document = _document()
    profile_id = parse_toml(document).active_profile

    with pytest.raises(ConfigValidationError):
        set_dpi_stages(document, profile_id, [(99, 400)], 1)
    with pytest.raises(ConfigValidationError):
        set_dpi_stages(document, profile_id, [(400, 400)], 2)
    with pytest.raises(ConfigValidationError):
        set_dpi_stages(document, profile_id, [], 1)
    with pytest.raises(KeyError):
        set_dpi_stages(document, "missing", [(400, 400)], 1)


def test_edit_profile_round_trips_display_names() -> None:
    document = _document()
    profile_id = parse_toml(document).active_profile

    def rename(profile: Profile) -> Profile:
        return replace(profile, display_name="Renamed")

    updated = edit_profile(document, profile_id, rename)

    configuration = parse_toml(updated)
    assert configuration.profile(profile_id).display_name == "Renamed"
    assert configuration.revision == parse_toml(document).revision + 1


def test_set_bindings_replaces_common_and_plate_actions() -> None:
    document = _document()
    configuration = parse_toml(document)
    profile_id = configuration.active_profile

    updated = set_bindings(
        document,
        profile_id,
        cast(
            dict[LogicalControlId, Action],
            {
                "dpi_up": MouseButtonAction(button="back"),
                "side_12_1": KeyAction(key="f12"),
                "ring_finger": DeviceAction(action="scroll_free_spin"),
            },
        ),
    )

    result = parse_toml(updated)
    profile = result.profile(profile_id)
    assert profile.bindings.action_for("dpi_up", profile.plate_layout) == MouseButtonAction(
        button="back"
    )
    assert profile.bindings.action_for("side_12_1", profile.plate_layout) == KeyAction(key="f12")
    assert profile.bindings.action_for("ring_finger", profile.plate_layout) == DeviceAction(
        action="scroll_free_spin"
    )
    assert result.revision == configuration.revision + 1


def test_set_bindings_rejects_unknown_controls() -> None:
    document = _document()
    profile_id = parse_toml(document).active_profile

    with pytest.raises(KeyError):
        set_bindings(
            document,
            profile_id,
            cast(dict[LogicalControlId, Action], {"side_99_1": KeyAction(key="f5")}),
        )


def test_set_bindings_none_removes_a_binding() -> None:
    document = _document()
    configuration = parse_toml(document)
    profile_id = configuration.active_profile

    updated = set_bindings(document, profile_id, {"dpi_up": None})

    profile = parse_toml(updated).profile(profile_id)
    assert profile.bindings.action_for("dpi_up", profile.plate_layout) is None


def test_set_scroll_and_power_round_trip() -> None:
    document = _document()
    profile_id = parse_toml(document).active_profile

    scrolled = set_scroll(document, profile_id, "free_spin", True, True)
    profile = parse_toml(scrolled).profile(profile_id)
    assert (profile.scroll.mode, profile.scroll.acceleration, profile.scroll.smart_reel) == (
        "free_spin",
        True,
        True,
    )

    powered = set_power(document, profile_id, 300, 15)
    profile = parse_toml(powered).profile(profile_id)
    assert (profile.power.idle_seconds, profile.power.low_battery_threshold) == (300, 15)
    assert parse_toml(powered).revision == parse_toml(document).revision + 1


def test_set_scroll_rejects_invalid_modes_through_the_domain() -> None:
    from typing import cast

    from naga_control.domain.profiles import ScrollMode

    document = _document()
    profile_id = parse_toml(document).active_profile

    with pytest.raises(ConfigValidationError):
        set_scroll(document, profile_id, cast(ScrollMode, "wild"), False, False)


def test_set_lighting_replaces_all_zones() -> None:
    document = _document()
    profile_id = parse_toml(document).active_profile
    lighting = LightingSettings(
        thumb_grid=LightingZone(
            brightness=50, effect=LightingEffect(kind="static", color=(255, 0, 0))
        ),
        logo=LightingZone(brightness=0, effect=LightingEffect(kind="off")),
        scroll_wheel=LightingZone(
            brightness=80, effect=LightingEffect(kind="wave", direction="left")
        ),
    )

    updated = set_lighting(document, profile_id, lighting)

    profile = parse_toml(updated).profile(profile_id)
    assert profile.lighting == lighting


def test_set_lighting_rejects_wave_on_the_thumb_grid() -> None:
    document = _document()
    profile_id = parse_toml(document).active_profile

    with pytest.raises(ConfigValidationError):
        lighting = LightingSettings(
            thumb_grid=LightingZone(
                brightness=50, effect=LightingEffect(kind="wave", direction="left")
            ),
            logo=LightingZone(brightness=0, effect=LightingEffect(kind="off")),
            scroll_wheel=LightingZone(brightness=0, effect=LightingEffect(kind="off")),
        )
        set_lighting(document, profile_id, lighting)


def test_duplicate_profile_adds_a_copy_with_new_identity() -> None:
    document = _document()
    configuration = parse_toml(document)

    updated = duplicate_profile(document, configuration.default_profile, "mmo", "MMO")

    result = parse_toml(updated)
    source = result.profile(configuration.default_profile)
    copy = result.profile("mmo")
    assert copy.display_name == "MMO"
    assert copy.dpi == source.dpi
    assert copy.bindings == source.bindings
    assert result.revision == configuration.revision + 1


def test_duplicate_profile_rejects_existing_ids_and_bad_slugs() -> None:
    document = _document()
    configuration = parse_toml(document)

    with pytest.raises(ConfigValidationError):
        duplicate_profile(
            document, configuration.default_profile, configuration.default_profile, "X"
        )
    with pytest.raises(ConfigValidationError):
        duplicate_profile(document, configuration.default_profile, "Bad Slug", "X")


def test_rename_profile_changes_only_the_display_name() -> None:
    document = _document()
    configuration = parse_toml(document)

    updated = rename_profile(document, configuration.default_profile, "Daily Driver")

    result = parse_toml(updated)
    assert result.profile(configuration.default_profile).display_name == "Daily Driver"
    assert [identifier for identifier, _ in result.profiles] == [
        identifier for identifier, _ in configuration.profiles
    ]


def test_remove_profile_reassigns_default_and_active_references() -> None:
    base = default_configuration()
    with_two = replace(
        base,
        profiles=(*base.profiles, ("mmo", base.profile(base.default_profile))),
        active_profile="mmo",
    )
    document = dump_toml(with_two)

    updated = remove_profile(document, "mmo")

    result = parse_toml(updated)
    assert [identifier for identifier, _ in result.profiles] == [base.default_profile]
    assert result.active_profile == base.default_profile
    assert result.default_profile == base.default_profile


def test_remove_profile_rejects_the_last_remaining_profile() -> None:
    document = _document()
    configuration = parse_toml(document)

    with pytest.raises(ConfigValidationError):
        remove_profile(document, configuration.profiles[0][0])
