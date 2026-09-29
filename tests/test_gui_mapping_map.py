import os
from collections.abc import Iterator
from typing import cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from naga_control.domain.actions import DeviceAction
from naga_control.gui.mapping_map import MappingMapView, mapping_image_path
from naga_control.gui.mapping_zones import MappingZone, zone_for_control


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


def test_clicking_a_zone_emits_its_control(qapp: QApplication) -> None:
    view = _view(qapp)
    selected: list[str] = []
    view.zone_selected.connect(selected.append)

    zone = zone_for_control("dpi_up")
    assert zone is not None
    _click_zone(qapp, view, zone)

    assert selected == ["dpi_up"]


def test_clicking_a_plate_zone_on_a_6_plate_does_not_emit(qapp: QApplication) -> None:
    view = _view(qapp)
    view.set_plate_layout(6)
    selected: list[str] = []
    view.zone_selected.connect(selected.append)

    zone = zone_for_control("side_12_1")
    assert zone is not None
    _click_zone(qapp, view, zone)

    assert selected == []


def test_clicking_the_passthrough_wheel_zone_does_not_emit(qapp: QApplication) -> None:
    view = _view(qapp)
    selected: list[str] = []
    view.zone_selected.connect(selected.append)

    from naga_control.gui.mapping_zones import WHEEL_CLICK_ZONE

    _click_zone(qapp, view, WHEEL_CLICK_ZONE)

    assert selected == []


def test_action_tooltips_reflect_bindings_and_plate(qapp: QApplication) -> None:
    view = _view(qapp)

    view.set_actions({"dpi_up": DeviceAction(action="dpi_stage_up"), "dpi_down": None})
    view.set_plate_layout(6)

    dpi_up = _item(view, "dpi_up")
    dpi_down = _item(view, "dpi_down")
    side_1 = _item(view, "side_12_1")
    wheel = _item(view, None)

    assert dpi_up.toolTip() == "DPI up — device: dpi_stage_up"  # type: ignore[attr-defined]
    assert dpi_down.toolTip() == "DPI down — passthrough"  # type: ignore[attr-defined]
    assert side_1.toolTip() == "Side 1 — not on the attached plate"  # type: ignore[attr-defined]
    assert wheel.toolTip() == "Scroll wheel click — passthrough (not remappable in v0.1)"  # type: ignore[attr-defined]


def test_selection_outlines_the_zone(qapp: QApplication) -> None:
    view = _view(qapp)

    view.set_selected("ring_finger")

    ring = _item(view, "ring_finger")
    dpi_up = _item(view, "dpi_up")
    assert ring.pen().widthF() == 3.0  # type: ignore[attr-defined]
    assert dpi_up.pen().style() == Qt.PenStyle.NoPen  # type: ignore[attr-defined]
