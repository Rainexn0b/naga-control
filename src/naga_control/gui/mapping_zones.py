"""Qt-free zone layout of the mapping illustration.

All rectangles are normalized (0..1) against the 1448x1086 source image
``assets/Mapping.png`` and were derived from its highlighted regions.
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
    plate: bool = False

    @property
    def assignable(self) -> bool:
        return self.control_id is not None

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
        MappingZone("dpi_up", "DPI up", _normalized(636, 136, 60, 80)),
        MappingZone("dpi_down", "DPI down", _normalized(636, 216, 60, 80)),
        MappingZone("wheel_tilt_left", "Wheel tilt left", _normalized(816, 212, 20, 84)),
        MappingZone("wheel_tilt_right", "Wheel tilt right", _normalized(920, 212, 20, 80)),
        MappingZone("top_front", "Top front", _normalized(856, 368, 48, 52)),
        MappingZone("top_rear", "Top rear", _normalized(856, 436, 48, 60)),
        MappingZone("ring_finger", "Ring finger", _normalized(1116, 288, 56, 196)),
    )


_PLATE12_PIXELS = (
    (188, 416, 40, 56),
    (240, 392, 32, 60),
    (288, 376, 44, 56),
    (200, 476, 44, 64),
    (256, 464, 32, 60),
    (308, 448, 32, 56),
    (216, 552, 32, 56),
    (268, 536, 40, 60),
    (324, 516, 40, 64),
    (232, 620, 44, 56),
    (284, 604, 40, 64),
    (336, 592, 36, 64),
)


def _plate12() -> tuple[MappingZone, ...]:
    return tuple(
        MappingZone(
            f"side_12_{number}",
            f"Side {number}",
            _normalized(*pixels),
            plate=True,
        )
        for number, pixels in enumerate(_PLATE12_PIXELS, start=1)
    )


WHEEL_CLICK_ZONE = MappingZone(
    None,
    "Scroll wheel click",
    _normalized(848, 192, 64, 144),
)

COMMON_ZONES: tuple[MappingZone, ...] = _common()
PLATE12_ZONES: tuple[MappingZone, ...] = _plate12()


def all_zones() -> tuple[MappingZone, ...]:
    """Every zone of the illustration, including the passthrough wheel click."""
    return (*COMMON_ZONES, WHEEL_CLICK_ZONE, *PLATE12_ZONES)


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
    """A zone can be assigned when it is a control on the attached plate."""
    if zone.control_id is None:
        return False
    return not (zone.plate and plate_layout != 12)
