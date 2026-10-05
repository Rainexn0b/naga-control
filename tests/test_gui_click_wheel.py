"""Wheel editing requires a direct click, not merely focus or a row jump."""

import os
from collections.abc import Iterator
from dataclasses import replace
from typing import cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_support import make_presenter, sync_run
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QWidget

from naga_control.config import dump_toml, parse_toml
from naga_control.gui.buttons_page import ButtonsPage
from naga_control.gui.click_wheel_combo import ClickWheelComboBox


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    yield cast(QApplication, QApplication.instance() or QApplication([]))


@pytest.fixture
def page(qapp: QApplication) -> Iterator[ButtonsPage]:
    presenter, model, _client = make_presenter("")
    widget = ButtonsPage(presenter, model, sync_run)
    sync_run(presenter.refresh)
    widget.resize(1100, 450)
    widget.show()
    widget.activateWindow()
    assert QTest.qWaitForWindowExposed(widget)
    qapp.processEvents()
    widget.rows_scroll.setFocus()
    qapp.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    qapp.processEvents()


@pytest.fixture(params=[False, True], ids=["action", "binding"])
def combo(request: pytest.FixtureRequest, page: ButtonsPage, qapp: QApplication) -> QComboBox:
    row = next(row for row in page.rows if row.control_id == "ring_finger")
    box = row.detail_edit if request.param else row.kind_box
    if box.isEditable():
        # Loaded bindings have only one option; append valid alternatives without editing.
        box.addItems(["left_control", "left_shift", "left_meta"])
    page.rows_scroll.ensureWidgetVisible(box)
    qapp.processEvents()
    assert isinstance(box, ClickWheelComboBox)
    assert box.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert box.currentIndex() < box.count() - 1
    return box


def _wheel(qapp: QApplication, target: QWidget) -> None:
    position = target.rect().center()
    window = target.window()
    handle = window.windowHandle()
    assert handle is not None
    assert window.childAt(target.mapTo(window, position)) is target
    event = QWheelEvent(
        QPointF(target.mapTo(window, position)),
        QPointF(target.mapToGlobal(position)),
        QPoint(),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    # Direct sendEvent is non-spontaneous and skips Qt's ignored-wheel propagation.
    QTest.wheelEvent(handle, event.position(), event.angleDelta(), event.pixelDelta())
    qapp.processEvents()


def _blocked(qapp: QApplication, page: ButtonsPage, combo: QComboBox) -> None:
    page.rows_scroll.ensureWidgetVisible(combo)
    qapp.processEvents()
    scrollbar = page.rows_scroll.verticalScrollBar()
    before_scroll = scrollbar.value()
    assert before_scroll < scrollbar.maximum()
    before = [(row.selected_kind(), row.selected_detail()) for row in page.rows]
    focus = qapp.focusWidget()
    status = page.status_label.text()
    assert not page.has_unsaved_changes()
    _wheel(qapp, combo.lineEdit() or combo)
    assert [(row.selected_kind(), row.selected_detail()) for row in page.rows] == before
    assert qapp.focusWidget() is focus, "Hovering with the wheel must not steal focus"
    assert scrollbar.value() > before_scroll, "Unarmed wheel must scroll the binding list"
    assert not page.has_unsaved_changes()
    assert not page.apply_button.isEnabled()
    assert not page.discard_button.isEnabled()
    assert page.status_label.text() == status


def _tab_focus(qapp: QApplication, page: ButtonsPage, combo: QComboBox) -> None:
    control = "ring_finger" if combo.isEditable() else "top_rear"
    previous = next(row.kind_box for row in page.rows if row.control_id == control)
    previous.setFocus()
    qapp.processEvents()
    QTest.keyClick(previous, Qt.Key.Key_Tab)
    qapp.processEvents()
    assert combo.hasFocus(), "The test must reach the editor via actual Tab navigation"


def _click(qapp: QApplication, combo: QComboBox) -> None:
    target = combo.lineEdit() or combo
    QTest.mouseClick(target, Qt.MouseButton.LeftButton, pos=target.rect().center())
    qapp.processEvents()
    if not combo.isEditable():
        assert combo.view().isVisible(), "A direct combo click should open its popup"
        combo.hidePopup()
        qapp.processEvents()
    assert combo.hasFocus(), "Closing the popup should restore focus to the clicked editor"


def test_unfocused_hover_scrolls_without_editing(
    qapp: QApplication, page: ButtonsPage, combo: QComboBox
) -> None:
    QTest.mouseMove(combo.lineEdit() or combo)
    qapp.processEvents()
    assert not combo.hasFocus()
    _blocked(qapp, page, combo)


@pytest.mark.parametrize("focus_method", ["programmatic", "tab"])
def test_focus_without_click_does_not_arm(
    qapp: QApplication, page: ButtonsPage, combo: QComboBox, focus_method: str
) -> None:
    if focus_method == "tab":
        _tab_focus(qapp, page, combo)
    else:
        combo.setFocus()
        qapp.processEvents()
    assert combo.hasFocus()
    _blocked(qapp, page, combo)


def test_artwork_jump_does_not_arm(qapp: QApplication, page: ButtonsPage) -> None:
    page.select_control("ring_finger")
    qapp.processEvents()
    combo = next(row.kind_box for row in page.rows if row.control_id == "ring_finger")
    assert combo.hasFocus()
    _blocked(qapp, page, combo)


def test_direct_click_arms_normal_wheel_editing(
    qapp: QApplication, page: ButtonsPage, combo: QComboBox
) -> None:
    before = combo.currentIndex()
    _click(qapp, combo)
    scrollbar = page.rows_scroll.verticalScrollBar()
    before_scroll = scrollbar.value()
    _wheel(qapp, combo.lineEdit() or combo)
    assert combo.currentIndex() == before + 1
    assert scrollbar.value() == before_scroll
    assert page.has_unsaved_changes()
    assert page.apply_button.isEnabled()


def test_focus_leaving_disarms_even_after_programmatic_return(
    qapp: QApplication, page: ButtonsPage, combo: QComboBox
) -> None:
    _click(qapp, combo)
    page.rows_scroll.setFocus()
    qapp.processEvents()
    assert not combo.hasFocus()
    combo.setFocus()
    qapp.processEvents()
    assert combo.hasFocus()
    _blocked(qapp, page, combo)


def test_keyboard_arrow_after_tab_still_edits(
    qapp: QApplication, page: ButtonsPage, combo: QComboBox
) -> None:
    _tab_focus(qapp, page, combo)
    before = combo.currentIndex()
    QTest.keyClick(combo, Qt.Key.Key_Down)
    qapp.processEvents()
    assert combo.currentIndex() == before + 1
    assert page.has_unsaved_changes()


def test_explicit_popup_scroll_and_selection_remain_normal(
    qapp: QApplication, page: ButtonsPage, combo: QComboBox
) -> None:
    combo.addItems([f"option_{number}" for number in range(100)])
    combo.setMaxVisibleItems(6)
    before = combo.currentIndex()
    combo.setFocus()
    QTest.keyClick(combo, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
    qapp.processEvents()
    view = combo.view()
    assert view.isVisible()
    scrollbar = view.verticalScrollBar()
    before_scroll = scrollbar.value()
    assert scrollbar.maximum() > before_scroll
    _wheel(qapp, view.viewport())
    assert scrollbar.value() > before_scroll
    assert combo.currentIndex() == before
    assert not page.has_unsaved_changes()
    model = view.model()
    assert model is not None
    index = model.index(before + 1, 0)
    view.scrollTo(index)
    qapp.processEvents()
    QTest.mouseClick(
        view.viewport(), Qt.MouseButton.LeftButton, pos=view.visualRect(index).center()
    )
    qapp.processEvents()
    assert not view.isVisible()
    assert combo.currentIndex() == before + 1
    assert page.has_unsaved_changes()


def test_reloaded_rows_start_unarmed(
    qapp: QApplication, page: ButtonsPage, combo: QComboBox
) -> None:
    editable = combo.isEditable()
    _click(qapp, combo)
    document = page.model.configuration_document
    assert document is not None
    configuration = parse_toml(document)
    updated = replace(configuration, revision=configuration.revision + 1)
    page.model.apply_configuration(updated.revision, dump_toml(updated))
    qapp.processEvents()
    row = next(row for row in page.rows if row.control_id == "ring_finger")
    replacement = row.detail_edit if editable else row.kind_box
    assert replacement is not combo
    assert isinstance(replacement, ClickWheelComboBox)
    if editable:
        replacement.addItems(["left_control", "left_shift"])
    replacement.setFocus()
    qapp.processEvents()
    assert replacement.hasFocus()
    _blocked(qapp, page, replacement)
