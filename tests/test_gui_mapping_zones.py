from naga_control.gui.mapping_zones import (
    MappingZone,
    all_zones,
    zone_assignable,
    zone_at,
    zone_for_control,
    zone_for_key,
)


def test_the_sidecar_defines_every_control_zone() -> None:
    zones = all_zones()

    control_ids = {zone.control_id for zone in zones if zone.control_id is not None}
    assert len(zones) == 30
    expected_common = {
        "dpi_up",
        "dpi_down",
        "wheel_tilt_left",
        "wheel_tilt_right",
        "top_front",
        "top_rear",
        "ring_finger",
    }
    assert expected_common <= control_ids
    for number in range(1, 13):
        assert f"side_12_{number}" in control_ids
    for number in range(1, 7):
        assert f"side_6_{number}" in control_ids
    assert "side_2_front" in control_ids
    assert "side_2_rear" in control_ids


def test_decorative_main_regions_are_passthrough() -> None:
    wheel = zone_for_key("main.wheel")
    primary_left = zone_for_key("main.primary_left")
    primary_right = zone_for_key("main.primary_right")

    assert wheel is not None and wheel.control_id is None
    assert primary_left is not None and primary_left.control_id is None
    assert primary_right is not None and primary_right.control_id is None
    assert not zone_assignable(wheel, 12)
    assert not zone_assignable(primary_left, 12)


def test_zone_rects_are_normalized_and_sized() -> None:
    for zone in all_zones():
        x, y, w, h = zone.rect
        assert 0.0 <= x < 1.0, zone
        assert 0.0 <= y < 1.0, zone
        assert 0.003 < w < 0.4, zone
        assert 0.003 < h < 0.4, zone
        assert x + w <= 1.0 + 1e-9, zone
        assert y + h <= 1.0 + 1e-9, zone


def test_zone_centers_hit_their_own_zone() -> None:
    for zone in all_zones():
        x, y, w, h = zone.rect
        assert zone_at(x + w / 2, y + h / 2) is zone


def test_the_dpi_pair_is_two_separate_zones() -> None:
    front = zone_for_control("dpi_up")
    rear = zone_for_control("dpi_down")
    assert front is not None and rear is not None
    assert front.plate is None and rear.plate is None
    assert zone_at(*_center(front)) is front
    assert zone_at(*_center(rear)) is rear


def test_plate_zones_are_always_assignable() -> None:
    expectations = [
        ("side_12_1", 12),
        ("side_6_1", 6),
        ("side_2_front", 2),
    ]
    for control_id, plate in expectations:
        zone = zone_for_control(control_id)
        assert zone is not None and zone.plate == plate
        for layout in (2, 6, 12):
            assert zone_assignable(zone, layout)

    dpi_up = zone_for_control("dpi_up")
    assert dpi_up is not None
    for layout in (2, 6, 12):
        assert zone_assignable(dpi_up, layout)


def test_sideplate_numbering_matches_the_physical_plate() -> None:
    expectations = {
        "side12.r1c1": "side_12_3",
        "side12.r2c1": "side_12_2",
        "side12.r3c1": "side_12_1",
        "side12.r1c4": "side_12_12",
        "side12.r2c3": "side_12_8",
        "side12.r3c4": "side_12_10",
        "side6.r1c1": "side_6_1",
        "side6.r1c3": "side_6_3",
        "side6.r2c1": "side_6_6",
        "side6.r2c3": "side_6_4",
        "side2.r1c1": "side_2_front",
        "side2.r1c2": "side_2_rear",
    }
    for region_key, control_id in expectations.items():
        zone = zone_for_key(region_key)
        assert zone is not None and zone.control_id == control_id, region_key

    one = zone_for_control("side_12_1")
    three = zone_for_control("side_12_3")
    assert one is not None and three is not None
    assert one.rect[1] > three.rect[1]


def _center(zone: "MappingZone") -> tuple[float, float]:
    x, y, w, h = zone.rect
    return (x + w / 2, y + h / 2)
