"""Pure configuration transforms for the calibration session."""

from dataclasses import replace

from naga_control.domain.hardware import HardwareState
from naga_control.domain.profiles import (
    Bindings,
    Configuration,
    DpiSettings,
    DpiStage,
    ScrollSettings,
)


def passthrough_configuration(configuration: Configuration) -> Configuration:
    empty = Bindings(common=(), plate_2=(), plate_6=(), plate_12=())
    profiles = tuple(
        (identifier, replace(profile, bindings=empty))
        if identifier == configuration.active_profile
        else (identifier, profile)
        for identifier, profile in configuration.profiles
    )
    return replace(configuration, profiles=profiles)


def adopt_observed_settings(
    configuration: Configuration, state: HardwareState | None
) -> Configuration | None:
    if state is None or state.status != "available":
        return None
    if (
        not state.dpi_stages
        or state.scroll_mode is None
        or state.scroll_acceleration is None
        or state.scroll_smart_reel is None
    ):
        return None
    dpi = DpiSettings(
        stages=tuple(DpiStage(stage.x, stage.y) for stage in state.dpi_stages),
        active_stage=state.active_dpi_stage or 1,
    )
    scroll = ScrollSettings(
        mode=state.scroll_mode,
        acceleration=state.scroll_acceleration,
        smart_reel=state.scroll_smart_reel,
    )
    profiles = tuple(
        (identifier, replace(profile, dpi=dpi, scroll=scroll))
        if identifier == configuration.active_profile
        else (identifier, profile)
        for identifier, profile in configuration.profiles
    )
    return replace(configuration, profiles=profiles, revision=configuration.revision + 1)
