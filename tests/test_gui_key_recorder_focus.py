"""Recorder application event-filter ownership and the live Shift+Tab repro.

Live-GUI validation showed Shift+Tab alone is consumed by Qt backward focus
traversal while Record is active. While recording, the recorder installs
itself as an application event filter and consumes KeyPress/KeyRelease there.
Application filters run inside ``notify_helper`` before the target object
(including ``QWidgetWindow``) processes the event, so the Backtab press never
reaches traversal and focus stays on the recorder. Cancelling (Escape,
completion, or focus loss) removes the filter exactly once.
"""

import os
from collections.abc import Iterator
from typing import cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QVBoxLayout, QWidget

from naga_control.gui.key_recorder import KeyRecorder


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    yield cast(QApplication, app)


def _recorded(recorder: KeyRecorder) -> list[tuple[str, str]]:
    recorded: list[tuple[str, str]] = []

    def store(kind: str, detail: str) -> None:
        recorded.append((kind, detail))

    recorder.recorded.connect(store)
    return recorded


def _dialog() -> tuple[QDialog, KeyRecorder, QLineEdit]:
    dialog = QDialog()
    layout = QVBoxLayout(dialog)
    recorder = KeyRecorder()
    other = QLineEdit()
    layout.addWidget(recorder)
    layout.addWidget(other)
    return dialog, recorder, other


def _send(
    app: QApplication,
    target: QWidget,
    event_type: QEvent.Type,
    key: Qt.Key,
    modifiers: Qt.KeyboardModifier,
    text: str = "",
) -> None:
    app.sendEvent(target, QKeyEvent(event_type, key, modifiers, 0, 0, 0, text))


def test_sibling_key_is_consumed_while_recording(qapp: QApplication) -> None:
    dialog, recorder, other = _dialog()
    recorded = _recorded(recorder)
    other.setText("abc")
    try:
        dialog.show()
        qapp.processEvents()
        QTest.mouseClick(recorder, Qt.MouseButton.LeftButton)
        qapp.processEvents()
        assert recorder.text() == "Press keys…"

        _send(
            qapp, other, QEvent.Type.KeyPress, Qt.Key.Key_Backspace, Qt.KeyboardModifier.NoModifier
        )
        _send(
            qapp,
            other,
            QEvent.Type.KeyRelease,
            Qt.Key.Key_Backspace,
            Qt.KeyboardModifier.NoModifier,
        )

        assert recorded == [("key", "backspace")]
        assert other.text() == "abc"
    finally:
        recorder.cancel()
        dialog.close()


def test_sibling_keys_pass_through_after_completion(qapp: QApplication) -> None:
    dialog, recorder, other = _dialog()
    recorded = _recorded(recorder)
    other.setText("abc")
    other.setCursorPosition(len(other.text()))
    try:
        dialog.show()
        qapp.processEvents()
        QTest.mouseClick(recorder, Qt.MouseButton.LeftButton)
        qapp.processEvents()
        _send(qapp, recorder, QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier)

        assert recorded == [("key", "a")]

        _send(
            qapp, other, QEvent.Type.KeyPress, Qt.Key.Key_Backspace, Qt.KeyboardModifier.NoModifier
        )

        assert recorded == [("key", "a")]
        assert other.text() == "ab"
    finally:
        recorder.cancel()
        dialog.close()


def test_sibling_keys_pass_through_after_escape(qapp: QApplication) -> None:
    dialog, recorder, other = _dialog()
    recorded = _recorded(recorder)
    other.setText("abc")
    other.setCursorPosition(len(other.text()))
    try:
        dialog.show()
        qapp.processEvents()
        QTest.mouseClick(recorder, Qt.MouseButton.LeftButton)
        qapp.processEvents()
        _send(
            qapp, recorder, QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
        )

        assert recorder.text() == "Record"
        assert recorded == []

        _send(
            qapp, other, QEvent.Type.KeyPress, Qt.Key.Key_Backspace, Qt.KeyboardModifier.NoModifier
        )

        assert recorded == []
        assert other.text() == "ab"
    finally:
        recorder.cancel()
        dialog.close()


def test_focused_widget_path_records_exactly_once(qapp: QApplication) -> None:
    dialog, recorder, _other = _dialog()
    recorded = _recorded(recorder)
    try:
        dialog.show()
        qapp.processEvents()
        QTest.mouseClick(recorder, Qt.MouseButton.LeftButton)
        qapp.processEvents()
        _send(qapp, recorder, QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier)
        _send(qapp, recorder, QEvent.Type.KeyRelease, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier)

        assert recorded == [("key", "a")]
    finally:
        recorder.cancel()
        dialog.close()


def test_shift_tab_recording_path_has_no_regression(qapp: QApplication) -> None:
    # Direct-delivery non-regression: a Backtab press sent to the recorder is
    # consumed by the application event filter and records the chord.
    recorder = KeyRecorder()
    recorded = _recorded(recorder)
    recorder.click()
    _send(
        qapp,
        recorder,
        QEvent.Type.KeyPress,
        Qt.Key.Key_Backtab,
        Qt.KeyboardModifier.ShiftModifier,
    )

    assert recorded == [("key_combo", "left_shift+tab")]
    assert recorder.text() == "Record"


def test_live_shift_tab_records_without_losing_focus(qapp: QApplication) -> None:
    dialog, recorder, _other = _dialog()
    recorded = _recorded(recorder)
    try:
        dialog.show()
        qapp.processEvents()
        dialog.activateWindow()
        qapp.processEvents()
        QTest.mouseClick(recorder, Qt.MouseButton.LeftButton)
        qapp.processEvents()
        assert qapp.focusWidget() is recorder

        QTest.keyClick(
            dialog.windowHandle(),
            Qt.Key.Key_Backtab,
            Qt.KeyboardModifier.ShiftModifier,
        )
        qapp.processEvents()

        assert recorded == [("key_combo", "left_shift+tab")]
        assert qapp.focusWidget() is recorder
    finally:
        recorder.cancel()
        dialog.close()
