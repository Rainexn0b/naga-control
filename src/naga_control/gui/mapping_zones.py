"""Qt-free zone layout of the mapping illustration.

All rectangles are normalized (0..1) against the 1448x1086 source image
``assets/Mapping.png``. The image shows the main mouse on the right (common
controls plus a decorative attached 12-button grid) and, on the left, the
three side plates: 12-button (4x3), 6-button (3x2), and 2-button.
"""

from dataclasses import dataclass

_IMAGE_WIDTH = 1448
_IMAGE_HEIGHT = 1086


@dataclass(frozen=True)
class MappingZone:
    """One clickable region of the mapping illustration."""

    control_id: str | None
    label: str
    rect: tuple[float, float, float, float]
    plate: int | None = None

    def contains(self, x: float, y: float) -> bool:
        rx, ry, rw, rh = self.rect
        return rx <= x < rx + rw and ry <= y < ry + rh


def _normalized(x: int, y: int, w: int, h: int, pad: int = 4) -> tuple[float, float, float, float]:
    px, py = x - pad, y - pad
    pw, ph = w + 2 * pad, h + 2 * pad
    return (
        max(0.0, px / _IMAGE_WIDTH),
        max(0.0, py / _IMAGE_HEIGHT),
        min(1.0, pw / _IMAGE_WIDTH),
        min(1.0, ph / _IMAGE_HEIGHT),
    )


def _common() -> tuple[MappingZone, ...]:
    return (
        MappingZone("dpi_up", "DPI up", _normalized(676, 204, 46, 46)),
        MappingZone("dpi_down", "DPI down", _normalized(676, 250, 46, 44)),
        MappingZone("wheel_tilt_left", "Wheel tilt left", _normalized(840, 208, 16, 84)),
        MappingZone("wheel_tilt_right", "Wheel tilt right", _normalized(944, 208, 20, 84)),
        MappingZone("top_front", "Top front", _normalized(880, 368, 44, 52)),
        MappingZone("top_rear", "Top rear", _normalized(880, 440, 44, 56)),
        MappingZone("ring_finger", "Ring finger", _normalized(1140, 284, 56, 200)),
    )


def _plate12() -> tuple[MappingZone, ...]:
    boxes = (
        (252, 230, 36, 34),
        (296, 228, 36, 34),
        (338, 228, 36, 34),
        (378, 226, 38, 34),
        (256, 270, 36, 32),
        (300, 268, 36, 32),
        (342, 266, 36, 32),
        (384, 264, 36, 32),
        (262, 308, 36, 34),
        (304, 306, 36, 34),
        (348, 304, 36, 34),
        (390, 302, 34, 34),
    )
    return tuple(
        MappingZone(f"side_12_{number}", f"Side {number}", _normalized(*box), plate=12)
        for number, box in enumerate(boxes, start=1)
    )


def _plate6() -> tuple[MappingZone, ...]:
    boxes = (
        (258, 452, 48, 38),
        (308, 452, 46, 36),
        (360, 450, 50, 38),
        (262, 494, 44, 34),
        (314, 492, 42, 32),
        (366, 492, 44, 32),
    )
    return tuple(
        MappingZone(f"side_6_{number}", f"Side {number}", _normalized(*box), plate=6)
        for number, box in enumerate(boxes, start=1)
    )


def _plate2() -> tuple[MappingZone, ...]:
    return (
        MappingZone("side_2_front", "Side front", _normalized(264, 684, 62, 46), plate=2),
        MappingZone("side_2_rear", "Side rear", _normalized(334, 682, 46, 46), plate=2),
    )


WHEEL_CLICK_ZONE = MappingZone(
    None,
    "Scroll wheel click",
    _normalized(868, 188, 64, 148),
)

MAIN_GRID_HINT_ZONE = MappingZone(
    None,
    "Side buttons",
    _normalized(592, 408, 160, 300),
)

COMMON_ZONES: tuple[MappingZone, ...] = _common()
PLATE_ZONES: tuple[MappingZone, ...] = (*_plate12(), *_plate6(), *_plate2())


def all_zones() -> tuple[MappingZone, ...]:
    """Every zone, including decorative passthrough regions."""
    return (*COMMON_ZONES, WHEEL_CLICK_ZONE, MAIN_GRID_HINT_ZONE, *PLATE_ZONES)


def zone_at(x: float, y: float, *, plate_layout: int = 12) -> MappingZone | None:
    """Return the zone containing a normalized point, if any."""
    for zone in all_zones():
        if zone.contains(x, y):
            return zone
    return None


def zone_for_control(control_id: str) -> MappingZone | None:
    for zone in all_zones():
        if zone.control_id == control_id:
            return zone
    return None


def zone_assignable(zone: MappingZone, plate_layout: int) -> bool:
    """A zone can be assigned when its plate is the attached one."""
    if zone.control_id is None:
        return False
    return zone.plate is None or zone.plate == plate_layout
