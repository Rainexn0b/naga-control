import hashlib
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsSimpleTextItem

from naga_control.domain.actions import DeviceAction
from naga_control.gui.mapping_map import MappingMapView, mapping_image_path
from naga_control.gui.mapping_zones import (
    MappingZone,
    regions_path,
    zone_at,
    zone_for_control,
)


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    yield cast(QApplication, app)


def _view(qapp: QApplication) -> MappingMapView:
    view = MappingMapView()
    view.resize(600, 500)
    view.show()
    qapp.processEvents()
    return view


def _item(view: MappingMapView, control_id: str | None) -> object:
    return next(
        item
        for item in view.zone_items
        if item.zone.control_id == control_id  # type: ignore[attr-defined]
    )


def _item_by_key(view: MappingMapView, region_key: str) -> object:
    return next(
        item
        for item in view.zone_items
        if item.zone.region_key == region_key  # type: ignore[attr-defined]
    )


def _click_zone(qapp: QApplication, view: MappingMapView, zone: MappingZone) -> None:
    x, y, w, h = zone.rect
    scene_point = QPointF(
        view.pixmap_item.pixmap().width() * (x + w / 2),
        view.pixmap_item.pixmap().height() * (y + h / 2),
    )
    view_point = view.mapFromScene(scene_point)
    viewport_point = view.viewport().mapFrom(view, view_point)
    QTest.mouseClick(
        view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, viewport_point
    )
    qapp.processEvents()


def test_bundled_mapping_image_loads() -> None:
    from PySide6.QtGui import QImage

    image = QImage(str(mapping_image_path()))
    assert not image.isNull()
    assert image.width() == 1448 and image.height() == 1086


def test_bundled_regions_match_the_preview_and_source_mask() -> None:
    from PySide6.QtGui import QImage

    source = Path(__file__).resolve().parents[1] / "assets"
    mask_path = source / "Mapping.mask.png"
    mask = QImage(str(mask_path))
    document = json.loads(regions_path().read_text(encoding="utf-8"))
    size = (mask.width(), mask.height())
    assert size == (1448, 1086)
    assert size == (
        document["coordinate_system"]["width"],
        document["coordinate_system"]["height"],
    )
    assert hashlib.sha256(mask_path.read_bytes()).hexdigest() == document["mask"]["sha256"]
    assert (
        hashlib.sha256(mapping_image_path().read_bytes()).hexdigest()
        == document["artwork"]["sha256"]
    )

    for region in cast("list[dict[str, Any]]", document["regions"]):
        x, y = region["label_anchor_px"]
        color = mask.pixelColor(x, y)
        assert (color.red(), color.green(), color.blue()) == tuple(region["rgb"])
        zone = zone_at((x + 0.5) / size[0], (y + 0.5) / size[1])
        assert zone is not None and zone.region_key == region["region_key"]


def test_drawn_numbers_match_side_button_anchors_and_remain_click_through(
    qapp: QApplication,
) -> None:
    view = _view(qapp)
    labels = {
        int(item.text()): item
        for item in view.pixmap_item.childItems()
        if isinstance(item, QGraphicsSimpleTextItem)
    }
    assert set(labels) == set(range(1, 31))
    zone = zone_for_control("side_12_1")
    assert zone is not None
    label = labels[11]
    center = label.pos() + label.boundingRect().center()
    assert center.x() == pytest.approx(zone.anchor[0] * view.pixmap_item.pixmap().width())
    assert center.y() == pytest.approx(zone.anchor[1] * view.pixmap_item.pixmap().height())
    assert label.acceptedMouseButtons() == Qt.MouseButton.NoButton
    assert label.font().pixelSize() == 21
    assert label.pen().widthF() < 1

    rear = zone_for_control("top_rear")
    assert rear is not None and rear.number == 9
    rear_center = labels[9].pos() + labels[9].boundingRect().center()
    assert rear_center.x() == pytest.approx(rear.anchor[0] * view.pixmap_item.pixmap().width())
    assert rear_center.y() == pytest.approx(rear.anchor[1] * view.pixmap_item.pixmap().height())

    selected: list[str] = []
    view.zone_selected.connect(selected.append)
    view_point = view.mapFromScene(center)
    viewport_point = view.viewport().mapFrom(view, view_point)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=viewport_point)
    assert selected == ["side_12_1"]


def test_clicking_a_zone_emits_its_control(qapp: QApplication) -> None:
    view = _view(qapp)
    selected: list[str] = []
    view.zone_selected.connect(selected.append)

    zone = zone_for_control("dpi_up")
    assert zone is not None
    _click_zone(qapp, view, zone)

    assert selected == ["dpi_up"]


def test_clicking_any_plate_zone_emits_regardless_of_profile(qapp: QApplication) -> None:
    view = _view(qapp)
    selected: list[str] = []
    view.zone_selected.connect(selected.append)

    zone = zone_for_control("side_12_1")
    assert zone is not None
    _click_zone(qapp, view, zone)
    _click_zone(qapp, view, zone_for_control("side_6_4") or zone)

    assert selected == ["side_12_1", "side_6_4"]


def test_clicking_the_passthrough_wheel_zone_does_not_emit(qapp: QApplication) -> None:
    view = _view(qapp)
    selected: list[str] = []
    view.zone_selected.connect(selected.append)

    from naga_control.gui.mapping_zones import zone_for_key

    wheel = zone_for_key("main.wheel")
    assert wheel is not None
    _click_zone(qapp, view, wheel)

    assert selected == []


def test_action_tooltips_reflect_bindings_and_plate(qapp: QApplication) -> None:
    view = _view(qapp)

    view.set_actions({"dpi_up": DeviceAction(action="dpi_stage_up"), "dpi_down": None})

    dpi_up = _item(view, "dpi_up")
    dpi_down = _item(view, "dpi_down")
    side_1 = _item(view, "side_12_1")
    wheel = _item_by_key(view, "main.wheel")

    assert dpi_up.toolTip() == "DPI up — device: dpi_stage_up"  # type: ignore[attr-defined]
    assert dpi_down.toolTip() == "DPI down — passthrough"  # type: ignore[attr-defined]
    assert side_1.toolTip() == "Side 1 — passthrough"  # type: ignore[attr-defined]
    assert wheel.toolTip().endswith("— passthrough (not remappable in v0.1)")  # type: ignore[attr-defined]


def test_all_plates_are_equally_visible_and_clickable(qapp: QApplication) -> None:
    view = _view(qapp)

    side_12 = _item(view, "side_12_1")
    side_6 = _item(view, "side_6_1")
    assert side_12.opacity() == 1.0  # type: ignore[attr-defined]
    assert side_6.opacity() == 1.0  # type: ignore[attr-defined]
    assert side_12.isEnabled()  # type: ignore[attr-defined]


def test_selection_outlines_the_zone(qapp: QApplication) -> None:
    view = _view(qapp)

    view.set_selected("ring_finger")

    ring = _item(view, "ring_finger")
    dpi_up = _item(view, "dpi_up")
    assert ring.pen().widthF() == 3.0  # type: ignore[attr-defined]
    assert dpi_up.pen().style() == Qt.PenStyle.NoPen  # type: ignore[attr-defined]
