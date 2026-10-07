"""Draft builders and checker for mouse-settings page tests."""

from dataclasses import replace
from typing import cast

from naga_control.domain.profiles import (
    DpiSettings,
    DpiStage,
    LightingEffect,
    LightingSettings,
    LightingZone,
    Profile,
    ScrollSettings,
)
from naga_control.gui.mouse_settings_page import MouseSettingsPage


def edited(profile: Profile) -> Profile:
    return replace(
        profile,
        dpi=DpiSettings((DpiStage(2350, 2450), *profile.dpi.stages[1:]), 2),
        scroll=ScrollSettings("precision_tactile", True, True),
        lighting=LightingSettings(
            thumb_grid=LightingZone(31, LightingEffect("static", (12, 34, 56))),
            logo=LightingZone(42, LightingEffect("reactive", (65, 43, 21), speed=3)),
            scroll_wheel=LightingZone(53, LightingEffect("wave", direction="right")),
        ),
        poll_rate=500,
    )


def edit_all(page: MouseSettingsPage) -> None:
    page.dpi.rows[0].x_spin.setValue(2350)
    page.dpi.rows[0].y_spin.setValue(2450)
    page.dpi.active_box.setCurrentIndex(1)
    page.scroll_section.mode_box.setCurrentText("precision_tactile")
    page.scroll_section.acceleration_check.setChecked(True)
    page.scroll_section.smart_reel_check.setChecked(True)
    for row, brightness, kind, color in zip(
        page.lighting.rows,
        (31, 42, 53),
        ("static", "reactive", "wave"),
        ("12,34,56", "65,43,21", ""),
        strict=True,
    ):
        row.brightness_spin.setValue(brightness)
        row.kind_box.setCurrentText(kind)
        row.color_edit.setText(color)
    page.lighting.rows[1].speed_box.setCurrentText("3")
    page.lighting.rows[2].direction_box.setCurrentText("right")
    page.poll_rate_box.setCurrentIndex(page.poll_rate_box.findData(500))


def assert_values(page: MouseSettingsPage, profile: Profile) -> None:
    assert [(row.x_spin.value(), row.y_spin.value()) for row in page.dpi.rows] == [
        (stage.x, stage.y) for stage in profile.dpi.stages
    ]
    assert page.dpi.active_box.currentIndex() + 1 == profile.dpi.active_stage
    assert page.scroll_section.mode_box.currentText() == profile.scroll.mode
    assert page.scroll_section.acceleration_check.isChecked() == profile.scroll.acceleration
    assert page.scroll_section.smart_reel_check.isChecked() == profile.scroll.smart_reel
    assert page.poll_rate_box.currentData() == profile.poll_rate
    for row in page.lighting.rows:
        zone = cast(LightingZone, getattr(profile.lighting, row.zone))
        assert row.brightness_spin.value() == zone.brightness
        assert row.kind_box.currentText() == zone.effect.kind
        if zone.effect.color is not None:
            assert row.color_edit.text() == ",".join(str(value) for value in zone.effect.color)
        if zone.effect.speed is not None:
            assert row.speed_box.currentText() == str(zone.effect.speed)
        if zone.effect.direction is not None:
            assert row.direction_box.currentText() == zone.effect.direction
