import pytest

from naga_control.gui.mapping_zones import (
    WHEEL_CLICK_ZONE,
    all_zones,
    zone_assignable,
    zone_at,
    zone_for_control,
)


def test_the_illustration_defines_every_control_zone() -> None:
    zones = all_zones()

    control_ids = {zone.control_id for zone in zones if zone.control_id is not None}
    assert len(zones) == 7 + 12 + 1
    assert "dpi_up" in control_ids
    assert "dpi_down" in control_ids
    assert "wheel_tilt_left" in control_ids
    assert "wheel_tilt_right" in control_ids
    assert "top_front" in control_ids
    assert "top_rear" in control_ids
    assert "ring_finger" in control_ids
    for number in range(1, 13):
        assert f"side_12_{number}" in control_ids


def test_zone_rects_are_normalized_and_sized() -> None:
    for zone in all_zones():
        x, y, w, h = zone.rect
        assert 0.0 <= x < 1.0, zone
        assert 0.0 <= y < 1.0, zone
        assert 0.005 < w < 0.2, zone
        assert 0.005 < h < 0.3, zone
        assert x + w <= 1.0 + 1e-9, zone
        assert y + h <= 1.0 + 1e-9, zone


def test_zone_centers_hit_their_own_zone() -> None:
    for zone in all_zones():
        x, y, w, h = zone.rect
        assert zone_at(x + w / 2, y + h / 2) is zone


def test_the_dpi_pair_is_two_separate_zones() -> None:
    up = zone_for_control("dpi_up")
    down = zone_for_control("dpi_down")
    assert up is not None and down is not None
    ux, uy, uw, _uh = up.rect
    dx, dy, dw, _dh = down.rect
    assert (ux, uw) == (dx, dw)
    assert uy < dy
    assert zone_at(ux + uw / 2, uy + 0.01) is up
    assert zone_at(dx + dw / 2, dy + 0.01) is down


def test_the_wheel_click_zone_is_passthrough() -> None:
    assert WHEEL_CLICK_ZONE.control_id is None
    assert not zone_assignable(WHEEL_CLICK_ZONE, 12)
    x, y, w, h = WHEEL_CLICK_ZONE.rect
    assert zone_at(x + w / 2, y + h / 2) is WHEEL_CLICK_ZONE


def test_plate_zones_follow_the_attached_plate() -> None:
    side_1 = zone_for_control("side_12_1")
    assert side_1 is not None
    assert zone_assignable(side_1, 12)
    assert not zone_assignable(side_1, 6)
    assert not zone_assignable(side_1, 2)

    dpi_up = zone_for_control("dpi_up")
    assert dpi_up is not None
    assert zone_assignable(dpi_up, 2)
    assert zone_assignable(dpi_up, 6)
    assert zone_assignable(dpi_up, 12)


@pytest.mark.parametrize("control", ["top_front", "top_rear", "ring_finger"])
def test_center_top_zones_map_to_their_controls(control: str) -> None:
    zone = zone_for_control(control)
    assert zone is not None
    x, y, w, h = zone.rect
    hit = zone_at(x + w / 2, y + h / 2)
    assert hit is not None and hit.control_id == control
