from naga_control.gui.mapping_zones import (
    MAIN_GRID_HINT_ZONE,
    WHEEL_CLICK_ZONE,
    all_zones,
    zone_assignable,
    zone_at,
    zone_for_control,
)


def test_the_illustration_defines_every_control_zone() -> None:
    zones = all_zones()

    control_ids = {zone.control_id for zone in zones if zone.control_id is not None}
    assert len(zones) == 7 + 2 + 12 + 6 + 2
    assert "dpi_up" in control_ids
    assert "dpi_down" in control_ids
    assert "wheel_tilt_left" in control_ids
    assert "wheel_tilt_right" in control_ids
    assert "top_front" in control_ids
    assert "top_rear" in control_ids
    assert "ring_finger" in control_ids
    for number in range(1, 13):
        assert f"side_12_{number}" in control_ids
    for number in range(1, 7):
        assert f"side_6_{number}" in control_ids
    assert "side_2_front" in control_ids
    assert "side_2_rear" in control_ids


def test_the_two_decorative_zones_are_passthrough() -> None:
    assert WHEEL_CLICK_ZONE.control_id is None
    assert MAIN_GRID_HINT_ZONE.control_id is None
    assert not zone_assignable(WHEEL_CLICK_ZONE, 12)
    assert not zone_assignable(MAIN_GRID_HINT_ZONE, 12)


def test_zone_rects_are_normalized_and_sized() -> None:
    for zone in all_zones():
        x, y, w, h = zone.rect
        assert 0.0 <= x < 1.0, zone
        assert 0.0 <= y < 1.0, zone
        assert 0.003 < w < 0.2, zone
        assert 0.003 < h < 0.3, zone
        assert x + w <= 1.0 + 1e-9, zone
        assert y + h <= 1.0 + 1e-9, zone


def test_zone_centers_hit_their_own_zone() -> None:
    for zone in all_zones():
        x, y, w, h = zone.rect
        assert zone_at(x + w / 2, y + h / 2) is zone


def test_zone_rects_do_not_overlap_within_a_plate() -> None:
    zones = all_zones()
    tolerance = 0.008
    for index, zone in enumerate(zones):
        for other in zones[index + 1 :]:
            if zone.plate != other.plate:
                continue
            x, y, w, h = zone.rect
            ox, oy, ow, oh = other.rect
            overlap_x = min(x + w, ox + ow) - max(x, ox)
            overlap_y = min(y + h, oy + oh) - max(y, oy)
            separated = overlap_x <= tolerance or overlap_y <= tolerance
            assert separated, f"{zone} overlaps {other}"


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


def test_plate_zones_follow_the_attached_plate() -> None:
    expectations = [
        ("side_12_1", 12),
        ("side_6_1", 6),
        ("side_2_front", 2),
    ]
    for control_id, plate in expectations:
        zone = zone_for_control(control_id)
        assert zone is not None and zone.plate == plate
        assert zone_assignable(zone, plate)
        for other in (2, 6, 12):
            if other != plate:
                assert not zone_assignable(zone, other)

    dpi_up = zone_for_control("dpi_up")
    assert dpi_up is not None
    for layout in (2, 6, 12):
        assert zone_assignable(dpi_up, layout)
