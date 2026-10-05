"""Default desired configuration for a Naga V3 Pro profile."""

from naga_control.domain.actions import DeviceAction, KeyAction, MouseButtonAction
from naga_control.domain.profiles import (
    Binding,
    Bindings,
    Configuration,
    DpiSettings,
    DpiStage,
    LightingEffect,
    LightingSettings,
    LightingZone,
    PowerSettings,
    Profile,
    ScrollSettings,
    as_logical_control,
)


def default_configuration() -> Configuration:
    """Return a new immutable v1 configuration with Synapse-like bindings."""
    green = (0, 255, 0)
    profile = Profile(
        display_name="Default",
        plate_layout=12,
        bindings=Bindings(
            common=(
                Binding(as_logical_control("dpi_up"), DeviceAction("dpi_stage_up")),
                Binding(as_logical_control("dpi_down"), DeviceAction("dpi_stage_down")),
                Binding(as_logical_control("ring_finger"), KeyAction("left_alt")),
            ),
            plate_2=(
                Binding(as_logical_control("side_2_front"), MouseButtonAction("back")),
                Binding(as_logical_control("side_2_rear"), MouseButtonAction("forward")),
            ),
            plate_6=tuple(
                Binding(as_logical_control(f"side_6_{number}"), KeyAction(str(number)))
                for number in range(1, 7)
            ),
            plate_12=tuple(
                Binding(as_logical_control(f"side_12_{number}"), KeyAction(key))
                for number, key in enumerate(
                    ("1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "minus", "equal"),
                    start=1,
                )
            ),
        ),
        dpi=DpiSettings(
            stages=(
                DpiStage(800, 800),
                DpiStage(1600, 1600),
                DpiStage(2400, 2400),
                DpiStage(3200, 3200),
                DpiStage(5000, 5000),
            ),
            active_stage=2,
        ),
        scroll=ScrollSettings("tactile", acceleration=False, smart_reel=False),
        lighting=LightingSettings(
            thumb_grid=LightingZone(100, LightingEffect("static", color=green)),
            logo=LightingZone(100, LightingEffect("static", color=green)),
            scroll_wheel=LightingZone(100, LightingEffect("static", color=green)),
        ),
        power=PowerSettings(idle_seconds=300, low_battery_threshold=20),
    )
    return Configuration(
        revision=0,
        default_profile="default",
        active_profile="default",
        profiles=(("default", profile),),
        mode="software",
    )
