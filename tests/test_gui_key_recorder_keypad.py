"""Keypad-key recording keeps keypad identity instead of main-row tokens."""

import os
from collections.abc import Iterator
from typing import cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from naga_control.gui.key_recorder import KeyRecorder

KEYPAD = Qt.KeyboardModifier.KeypadModifier


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    yield cast(QApplication, app)


def _key(
    app: QApplication,
    recorder: KeyRecorder,
    event_type: QEvent.Type,
    key: Qt.Key,
    modifiers: Qt.KeyboardModifier,
    scan: int = 0,
    keysym: int = 0,
) -> None:
    app.sendEvent(recorder, QKeyEvent(event_type, key, modifiers, scan, keysym, 0, ""))


def _recorded(recorder: KeyRecorder) -> list[tuple[str, str]]:
    recorded: list[tuple[str, str]] = []

    def store(kind: str, detail: str) -> None:
        recorded.append((kind, detail))

    recorder.recorded.connect(store)
    return recorded


def test_ctrl_keypad_plus_records_ctrl_kp_plus_combo(qapp: QApplication) -> None:
    recorder = KeyRecorder()
    recorded = _recorded(recorder)
    recorder.click()
    modifiers = Qt.KeyboardModifier.ControlModifier | KEYPAD
    _key(qapp, recorder, QEvent.Type.KeyPress, Qt.Key.Key_Plus, modifiers)

    assert recorded == [("key_combo", "left_ctrl+kp_plus")]


def test_bare_keypad_plus_records_kp_plus_key(qapp: QApplication) -> None:
    recorder = KeyRecorder()
    recorded = _recorded(recorder)
    recorder.click()
    _key(qapp, recorder, QEvent.Type.KeyPress, Qt.Key.Key_Plus, KEYPAD)

    assert recorded == [("key", "kp_plus")]


def test_keypad_minus_records_kp_minus_key(qapp: QApplication) -> None:
    recorder = KeyRecorder()
    recorded = _recorded(recorder)
    recorder.click()
    _key(qapp, recorder, QEvent.Type.KeyPress, Qt.Key.Key_Minus, KEYPAD)

    assert recorded == [("key", "kp_minus")]


def test_keypad_5_records_kp_5_key(qapp: QApplication) -> None:
    recorder = KeyRecorder()
    recorded = _recorded(recorder)
    recorder.click()
    _key(qapp, recorder, QEvent.Type.KeyPress, Qt.Key.Key_5, KEYPAD)

    assert recorded == [("key", "kp_5")]


def test_keypad_enter_records_kp_enter_key(qapp: QApplication) -> None:
    recorder = KeyRecorder()
    recorded = _recorded(recorder)
    recorder.click()
    _key(qapp, recorder, QEvent.Type.KeyPress, Qt.Key.Key_Enter, KEYPAD)

    assert recorded == [("key", "kp_enter")]


def test_keypad_dot_records_kp_dot_key(qapp: QApplication) -> None:
    recorder = KeyRecorder()
    recorded = _recorded(recorder)
    recorder.click()
    _key(qapp, recorder, QEvent.Type.KeyPress, Qt.Key.Key_Period, KEYPAD)

    assert recorded == [("key", "kp_dot")]


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        (Qt.Key.Key_0, "kp_0"),
        (Qt.Key.Key_1, "kp_1"),
        (Qt.Key.Key_2, "kp_2"),
        (Qt.Key.Key_3, "kp_3"),
        (Qt.Key.Key_4, "kp_4"),
        (Qt.Key.Key_5, "kp_5"),
        (Qt.Key.Key_6, "kp_6"),
        (Qt.Key.Key_7, "kp_7"),
        (Qt.Key.Key_8, "kp_8"),
        (Qt.Key.Key_9, "kp_9"),
        (Qt.Key.Key_Period, "kp_dot"),
        (Qt.Key.Key_Plus, "kp_plus"),
        (Qt.Key.Key_Minus, "kp_minus"),
        (Qt.Key.Key_Asterisk, "kp_asterisk"),
        (Qt.Key.Key_Slash, "kp_slash"),
        (Qt.Key.Key_Enter, "kp_enter"),
    ],
)
def test_every_keypad_key_keeps_keypad_identity(
    qapp: QApplication, key: Qt.Key, expected: str
) -> None:
    recorder = KeyRecorder()
    recorded = _recorded(recorder)
    recorder.click()
    _key(qapp, recorder, QEvent.Type.KeyPress, key, KEYPAD)

    assert recorded == [("key", expected)]


def test_main_row_equal_with_shift_still_records_shift_equal(
    qapp: QApplication,
) -> None:
    recorder = KeyRecorder()
    recorded = _recorded(recorder)
    recorder.click()
    _key(
        qapp,
        recorder,
        QEvent.Type.KeyPress,
        Qt.Key.Key_Equal,
        Qt.KeyboardModifier.ShiftModifier,
    )

    assert recorded == [("key_combo", "left_shift+equal")]


def test_main_row_5_without_modifiers_records_5(qapp: QApplication) -> None:
    recorder = KeyRecorder()
    recorded = _recorded(recorder)
    recorder.click()
    _key(
        qapp,
        recorder,
        QEvent.Type.KeyPress,
        Qt.Key.Key_5,
        Qt.KeyboardModifier.NoModifier,
    )

    assert recorded == [("key", "5")]


def test_main_row_plus_without_shift_or_keypad_stays_unsupported(
    qapp: QApplication,
) -> None:
    recorder = KeyRecorder()
    recorded = _recorded(recorder)
    recorder.click()
    _key(
        qapp,
        recorder,
        QEvent.Type.KeyPress,
        Qt.Key.Key_Plus,
        Qt.KeyboardModifier.NoModifier,
    )

    assert recorded == []
    assert recorder.text() == "Unsupported key"
