import os
from collections.abc import Iterator
from typing import cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication

from naga_control.gui.models import ServiceModel, parse_snapshot
from naga_control.gui.tray_icon import TrayIcon, overlay_battery, tray_icon_path

SNAPSHOT_NO_BATTERY = '{"status":"available","generation":1,"transport":"hyperspeed","error":null}'
SNAPSHOT_BATTERY = (
    '{"status":"available","generation":1,"transport":"hyperspeed","error":null,'
    '"observed":{"battery_percent":42.0,"charging":false}}'
)


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    yield cast(QApplication, app)


def test_bundled_tray_icon_exists_and_is_square() -> None:
    image = QImage(str(tray_icon_path()))

    assert not image.isNull()
    assert image.width() == image.height()


def test_overlay_covers_the_bottom_half_only(qapp: QApplication) -> None:
    base = QImage(str(tray_icon_path()))
    top_before = base.pixelColor(2, 2)

    overlay = overlay_battery(base, 42)

    assert overlay.size() == base.size()
    assert overlay.pixelColor(2, 2) == top_before
    banner = overlay.pixelColor(base.width() // 2, base.height() - 2)
    assert banner.value() < 80


def test_overlay_is_deterministic(qapp: QApplication) -> None:
    base = QImage(str(tray_icon_path()))

    first = overlay_battery(base, 7)
    second = overlay_battery(base, 7)
    assert first == second

    different = overlay_battery(base, 99)
    assert first != different


def _tray(qapp: QApplication, model: ServiceModel) -> TrayIcon:
    toggles: list[bool] = []
    tray = TrayIcon(model, toggle_window=lambda: toggles.append(True), quit_app=lambda: None)
    return tray


def test_tray_updates_tooltip_and_icon_from_battery(qapp: QApplication) -> None:
    model = ServiceModel()
    tray = _tray(qapp, model)

    model.apply_snapshot(parse_snapshot(SNAPSHOT_NO_BATTERY))
    qapp.processEvents()
    assert tray.icon.toolTip() == "Naga Control — available · hyperspeed"
    assert not tray.icon.toolTip().endswith("%")

    model.apply_snapshot(parse_snapshot(SNAPSHOT_BATTERY))
    qapp.processEvents()
    assert tray.icon.toolTip() == "Naga Control — available · hyperspeed · 42%"


def test_tray_icon_carries_a_pixmap(qapp: QApplication) -> None:
    model = ServiceModel()
    tray = _tray(qapp, model)

    model.apply_snapshot(parse_snapshot(SNAPSHOT_BATTERY))
    qapp.processEvents()

    pixmap = tray.icon.icon().pixmap(64, 64)
    assert not QPixmap(pixmap).isNull()
