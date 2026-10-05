import os
from collections.abc import Iterator
from typing import cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from naga_control.gui.key_recorder import KeyRecorder


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


@pytest.mark.parametrize(
    ("key", "scan", "keysym", "expected"),
    [
        (Qt.Key.Key_Control, 105, 0, "right_ctrl"),
        (Qt.Key.Key_Control, 97, 0, "right_ctrl"),
        (Qt.Key.Key_Control, 0, 0xFFE4, "right_ctrl"),
        (Qt.Key.Key_Control, 37, 0, "left_ctrl"),
        (Qt.Key.Key_Alt, 108, 0, "right_alt"),
        (Qt.Key.Key_Alt, 100, 0, "right_alt"),
        (Qt.Key.Key_Alt, 0, 0xFFEA, "right_alt"),
        (Qt.Key.Key_Alt, 64, 0, "left_alt"),
        (Qt.Key.Key_AltGr, 108, 0, "right_alt"),
    ],
)
def test_recording_a_modifier_alone_preserves_its_side(
    qapp: QApplication, key: Qt.Key, scan: int, keysym: int, expected: str
) -> None:
    recorder = KeyRecorder()
    recorded = _recorded(recorder)
    recorder.click()
    modifier = (
        Qt.KeyboardModifier.ControlModifier
        if key == Qt.Key.Key_Control
        else Qt.KeyboardModifier.AltModifier
    )

    _key(qapp, recorder, QEvent.Type.KeyPress, key, modifier, scan, keysym)
    _key(qapp, recorder, QEvent.Type.KeyRelease, key, modifier, scan, keysym)

    assert recorded == [("key", expected)]


def test_shortcut_uses_recorded_right_control_and_left_alt(qapp: QApplication) -> None:
    recorder = KeyRecorder()
    recorded = _recorded(recorder)
    recorder.click()
    _key(
        qapp,
        recorder,
        QEvent.Type.KeyPress,
        Qt.Key.Key_Control,
        Qt.KeyboardModifier.ControlModifier,
        105,
    )
    both = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
    _key(qapp, recorder, QEvent.Type.KeyPress, Qt.Key.Key_Alt, both, 64)
    _key(qapp, recorder, QEvent.Type.KeyPress, Qt.Key.Key_T, both)

    assert recorded == [("key_combo", "right_ctrl+left_alt+t")]


def test_altgr_shortcut_does_not_invent_left_control(qapp: QApplication) -> None:
    recorder = KeyRecorder()
    recorded = _recorded(recorder)
    recorder.click()
    modifiers = (
        Qt.KeyboardModifier.ControlModifier
        | Qt.KeyboardModifier.AltModifier
        | Qt.KeyboardModifier.GroupSwitchModifier
    )
    _key(qapp, recorder, QEvent.Type.KeyPress, Qt.Key.Key_AltGr, modifiers, 108)
    _key(qapp, recorder, QEvent.Type.KeyPress, Qt.Key.Key_T, modifiers)

    assert recorded == [("key_combo", "right_alt+t")]
