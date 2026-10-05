"""The HSV picker is local to its dialog and independent of hardware state."""

import os
from collections.abc import Iterator
from typing import cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox

from naga_control.gui.color_wheel import ColorWheel, ColorWheelDialog


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    yield cast(QApplication, QApplication.instance() or QApplication([]))


def _close(qapp: QApplication, dialog: ColorWheelDialog) -> None:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_set_color_is_silent_and_keeps_hue_at_center(qapp: QApplication) -> None:
    wheel = ColorWheel()
    spy = QSignalSpy(wheel.colorChanged)
    wheel.setColor(QColor.fromHsv(120, 200, 184))
    assert spy.count() == 0
    wheel.show()
    qapp.processEvents()
    QTest.mouseClick(wheel, Qt.MouseButton.LeftButton, pos=QPoint(80, 80))
    assert wheel.color().saturation() == 0
    assert wheel.color().value() == 184
    assert wheel.color().hue() == 120
    assert spy.count() == 1
    wheel.setColor(QColor(110, 110, 110))
    assert wheel.color().hue() == 120
    assert spy.count() == 1
    wheel.close()


@pytest.mark.parametrize(
    ("point", "hue"),
    [
        (QPoint(150, 80), 0),
        (QPoint(80, 10), 90),
        (QPoint(10, 80), 180),
        (QPoint(80, 150), 270),
    ],
)
def test_mouse_quadrants(qapp: QApplication, point: QPoint, hue: int) -> None:
    wheel = ColorWheel()
    wheel.show()
    qapp.processEvents()
    QTest.mouseClick(wheel, Qt.MouseButton.LeftButton, pos=point)
    assert wheel.color().hue() == hue
    assert 220 <= wheel.color().saturation() <= 230
    wheel.close()


def test_drag_clamps_outside_disc_and_only_left_button_selects(qapp: QApplication) -> None:
    wheel = ColorWheel()
    wheel.show()
    qapp.processEvents()
    spy = QSignalSpy(wheel.colorChanged)
    QTest.mouseClick(wheel, Qt.MouseButton.RightButton, pos=QPoint(10, 80))
    assert spy.count() == 0
    QTest.mousePress(wheel, Qt.MouseButton.LeftButton, pos=QPoint(80, 80))
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(80, -15),
        QPointF(80, -15),
        QPointF(wheel.mapToGlobal(QPoint(80, -15))),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QCoreApplication.sendEvent(wheel, move)
    QTest.mouseRelease(wheel, Qt.MouseButton.LeftButton, pos=QPoint(80, -15))
    assert (wheel.color().hue(), wheel.color().saturation()) == (90, 255)
    assert spy.count() == 2
    wheel.close()


def test_disc_image_is_cached_and_marker_renders(qapp: QApplication) -> None:
    wheel = ColorWheel()
    assert wheel.size().width() == wheel.size().height() == 160
    wheel.show()
    qapp.processEvents()
    rendered = wheel.grab().toImage()
    assert rendered.pixelColor(145, 80).red() > 200
    assert rendered.pixelColor(80, 15).green() > 200
    assert rendered.pixelColor(15, 80).blue() > 180
    assert rendered.pixelColor(0, 0) == rendered.pixelColor(159, 0)
    assert rendered.pixelColor(154, 76).red() > 230
    assert rendered.pixelColor(154, 76).green() > 230
    wheel.setColor(QColor("blue"))
    qapp.processEvents()
    repainted = wheel.grab().toImage()
    assert repainted.pixelColor(145, 80) == rendered.pixelColor(145, 80)
    assert repainted.pixelColor(154, 76) != rendered.pixelColor(154, 76)
    wheel.close()


def test_dialog_value_roundtrip_and_swatch(qapp: QApplication) -> None:
    initial = QColor(42, 169, 221)
    dialog = ColorWheelDialog(initial)
    dialog.show()
    qapp.processEvents()
    assert dialog.isModal()
    assert dialog.value_slider.minimum() == 0
    assert dialog.value_slider.maximum() == 255
    for actual, expected in zip(
        (dialog.color().red(), dialog.color().green(), dialog.color().blue()),
        (initial.red(), initial.green(), initial.blue()),
        strict=True,
    ):
        assert abs(actual - expected) <= 2
    assert dialog.value_slider.value() == initial.value()
    spy = QSignalSpy(dialog.wheel.colorChanged)
    dialog.value_slider.setValue(0)
    assert dialog.color().value() == 0
    dialog.value_slider.setValue(initial.value())
    assert spy.count() == 0
    for actual, expected in zip(
        (dialog.color().red(), dialog.color().green(), dialog.color().blue()),
        (initial.red(), initial.green(), initial.blue()),
        strict=True,
    ):
        assert abs(actual - expected) <= 2
    assert dialog.color().name() in dialog.swatch.styleSheet()
    QTest.mouseClick(dialog.wheel, Qt.MouseButton.LeftButton, pos=QPoint(80, 10))
    assert dialog.color().hue() == 90
    assert dialog.color().value() == initial.value()
    assert dialog.color().name() in dialog.swatch.styleSheet()
    _close(qapp, dialog)


def test_cancel_does_not_change_callers_color(qapp: QApplication) -> None:
    external_color = QColor(40, 100, 200)
    dialog = ColorWheelDialog(external_color)
    dialog.show()
    qapp.processEvents()
    QTest.mouseClick(dialog.wheel, Qt.MouseButton.LeftButton, pos=QPoint(80, 10))
    dialog.value_slider.setValue(100)
    cancel = dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel)
    assert cancel is not None
    QTest.mouseClick(cancel, Qt.MouseButton.LeftButton)
    if dialog.result() == QDialog.DialogCode.Accepted:
        external_color = dialog.color()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert external_color == QColor(40, 100, 200)
    _close(qapp, dialog)


def test_ok_exposes_selected_color(qapp: QApplication) -> None:
    dialog = ColorWheelDialog(QColor("red"))
    dialog.show()
    qapp.processEvents()
    dialog.value_slider.setValue(80)
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert ok is not None
    QTest.mouseClick(ok, Qt.MouseButton.LeftButton)
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.color().value() == 80
    _close(qapp, dialog)
