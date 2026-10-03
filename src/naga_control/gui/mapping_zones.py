"""Qt-free zone layout loaded from the mapping sidecar.

The interactive zones come from ``assets/Mapping.regions.json`` (schema 1),
produced alongside the mapping artwork. Regions carry exact polygons and a
label anchor guaranteed inside the region; region keys map onto the
application control identifiers. Artwork updates need no code changes.
"""

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, cast

MAIN_CONTROL_KEYS: dict[str, str] = {
    "main.upper_left_front": "dpi_up",
    "main.upper_left_rear": "dpi_down",
    "main.wheel_tilt_left": "wheel_tilt_left",
    "main.wheel_tilt_right": "wheel_tilt_right",
    "main.top_front": "top_front",
    "main.top_rear": "top_rear",
    "main.ring_finger": "ring_finger",
}

_PASSTHROUGH_HINTS: dict[str, str] = {
    "main.wheel": "passthrough (not remappable in v0.1)",
    "main.primary_left": "not remappable in v0.1",
    "main.primary_right": "not remappable in v0.1",
}

PLATE_LABELS = {12: "12-button plate", 6: "6-button plate", 2: "2-button plate"}

Point = tuple[float, float]


@dataclass(frozen=True)
class MappingZone:
    """One clickable region of the mapping illustration."""

    control_id: str | None
    label: str
    rect: tuple[float, float, float, float]
    polygon: tuple[Point, ...]
    anchor: Point
    plate: int | None = None
    hint: str = ""
    region_key: str = ""

    def contains(self, x: float, y: float) -> bool:
        return _point_in_polygon(x, y, self.polygon)


def regions_path() -> Path:
    return Path(__file__).resolve().parent / "assets" / "Mapping.regions.json"


@cache
def all_zones() -> tuple[MappingZone, ...]:
    """Load every region from the bundled sidecar."""
    document = json.loads(regions_path().read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise ValueError("unsupported mapping sidecar schema")
    zones = tuple(_zone_from_region(region) for region in document["regions"])
    identifiers = [zone.control_id for zone in zones if zone.control_id is not None]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("mapping sidecar maps a control more than once")
    return zones


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


def zone_for_key(region_key: str) -> MappingZone | None:
    for zone in all_zones():
        if zone.region_key == region_key:
            return zone
    return None


def zone_assignable(zone: MappingZone, plate_layout: int) -> bool:
    """A zone can be assigned when its plate is the attached one."""
    if zone.control_id is None:
        return False
    return zone.plate is None or zone.plate == plate_layout


def _zone_from_region(region: dict[str, object]) -> MappingZone:
    bounds_raw = _field(region, "bounds_px_ltrb_exclusive")
    left, top, right, bottom = (float(value) for value in bounds_raw)
    width, height = 4096.0, 3072.0
    polygon = tuple(
        (float(point[0]) / width, float(point[1]) / height)
        for point in _field(region, "polygon_px")
    )
    anchor_raw = _field(region, "label_anchor_px")
    anchor = (float(anchor_raw[0]) / width, float(anchor_raw[1]) / height)
    key = str(region["region_key"])
    plate = region.get("sideplate_buttons")
    plate_layout = int(plate) if isinstance(plate, int) else None
    control_id = _control_for(key, region, plate_layout)
    label = _label_for(region, control_id, plate_layout)
    hint = "" if control_id is not None else _PASSTHROUGH_HINTS.get(key, "decorative")
    return MappingZone(
        control_id=control_id,
        label=label,
        rect=(left / width, top / height, (right - left) / width, (bottom - top) / height),
        polygon=polygon,
        anchor=anchor,
        plate=plate_layout,
        hint=hint,
        region_key=key,
    )


def _field(region: dict[str, object], name: str) -> list[Any]:
    value = region.get(name)
    if not isinstance(value, list):
        raise ValueError(f"mapping sidecar region lacks {name}")
    return cast("list[Any]", value)


def _control_for(key: str, region: dict[str, object], plate: int | None) -> str | None:
    if plate is None:
        return MAIN_CONTROL_KEYS.get(key)
    row, column = int(region["row"]), int(region["column"])  # type: ignore[index]
    if plate == 12:
        return f"side_12_{(row - 1) * 4 + column}"
    if plate == 6:
        return f"side_6_{(row - 1) * 3 + column}"
    if plate == 2:
        return "side_2_front" if column == 1 else "side_2_rear"
    return None


def _label_for(region: dict[str, object], control_id: str | None, plate: int | None) -> str:
    if control_id is not None:
        return _control_label(control_id)
    label = str(region.get("label") or region["region_key"])
    if plate is not None:
        return f"{label} ({PLATE_LABELS.get(plate, plate)})"
    return label


def _control_label(control_id: str) -> str:
    if control_id.startswith("side_"):
        parts = control_id.split("_")
        if parts[-1].isdigit():
            return f"Side {parts[-1]}"
        return f"Side {parts[-1]}"
    labels = {
        "dpi_up": "DPI up",
        "dpi_down": "DPI down",
        "wheel_tilt_left": "Wheel tilt left",
        "wheel_tilt_right": "Wheel tilt right",
        "top_front": "Top front",
        "top_rear": "Top rear",
        "ring_finger": "Ring finger",
    }
    return labels.get(control_id, control_id)


def _point_in_polygon(x: float, y: float, polygon: tuple[Point, ...]) -> bool:
    if not polygon:
        return False
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x0, y0 = previous
        x1, y1 = current
        if (y0 > y) != (y1 > y):
            crossing = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if x < crossing:
                inside = not inside
        previous = current
    return inside
