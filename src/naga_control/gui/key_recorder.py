"""Focused keyboard shortcut capture for the binding editor."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFocusEvent, QKeyEvent
from PySide6.QtWidgets import QPushButton

_KEYS: dict[int, str] = {
    Qt.Key.Key_Minus: "minus",
    Qt.Key.Key_Equal: "equal",
    Qt.Key.Key_BracketLeft: "left_brace",
    Qt.Key.Key_BraceLeft: "left_brace",
    Qt.Key.Key_BracketRight: "right_brace",
    Qt.Key.Key_BraceRight: "right_brace",
    Qt.Key.Key_Space: "space",
    Qt.Key.Key_Tab: "tab",
    Qt.Key.Key_Backtab: "tab",
    Qt.Key.Key_Backspace: "backspace",
    Qt.Key.Key_Return: "enter",
    Qt.Key.Key_Enter: "enter",
    Qt.Key.Key_Delete: "delete",
    Qt.Key.Key_Insert: "insert",
    Qt.Key.Key_Up: "up",
    Qt.Key.Key_Down: "down",
    Qt.Key.Key_Left: "left",
    Qt.Key.Key_Right: "right",
    Qt.Key.Key_Home: "home",
    Qt.Key.Key_End: "end",
    Qt.Key.Key_PageUp: "page_up",
    Qt.Key.Key_PageDown: "page_down",
}
_MODIFIER_KEYS: dict[int, str] = {
    Qt.Key.Key_Control: "left_ctrl",
    Qt.Key.Key_Alt: "left_alt",
    Qt.Key.Key_AltGr: "right_alt",
    Qt.Key.Key_Shift: "left_shift",
    Qt.Key.Key_Meta: "left_super",
}
_RIGHT_SCANS: dict[int, tuple[int, ...]] = {
    Qt.Key.Key_Control: (97, 105),
    Qt.Key.Key_Alt: (100, 108),
    Qt.Key.Key_Shift: (54, 62),
    Qt.Key.Key_Meta: (126, 134),
}
_RIGHT_KEYSYMS: dict[int, int] = {
    Qt.Key.Key_Control: 0xFFE4,
    Qt.Key.Key_Alt: 0xFFEA,
    Qt.Key.Key_Shift: 0xFFE2,
    Qt.Key.Key_Meta: 0xFFEC,
}
_MODIFIERS = (
    (Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Control, "left_ctrl"),
    (Qt.KeyboardModifier.AltModifier, Qt.Key.Key_Alt, "left_alt"),
    (Qt.KeyboardModifier.ShiftModifier, Qt.Key.Key_Shift, "left_shift"),
    (Qt.KeyboardModifier.MetaModifier, Qt.Key.Key_Meta, "left_super"),
)


def _key_token(key: int) -> str | None:
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z or Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        return chr(key).lower()
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F12:
        return f"f{key - Qt.Key.Key_F1 + 1}"
    return _KEYS.get(key)


def _modifier_token(event: QKeyEvent) -> str | None:
    token = _MODIFIER_KEYS.get(event.key())
    if token is not None and (
        event.nativeScanCode() in _RIGHT_SCANS.get(event.key(), ())
        or event.nativeVirtualKey() == _RIGHT_KEYSYMS.get(event.key())
    ):
        return token.replace("left_", "right_")
    return token


class KeyRecorder(QPushButton):
    """Record one key or modifier chord while this button owns keyboard focus."""

    recorded = Signal(str, str)

    def __init__(self) -> None:
        super().__init__("Record")
        self._recording = False
        self._held_modifiers: dict[int, str] = {}
        self._invalid_key = False
        self.setToolTip(
            "Click, then press a key or shortcut. Esc cancels. "
            "If a keyboard does not report modifier sides, edit the binding manually."
        )
        self.clicked.connect(self._toggle)

    def _toggle(self) -> None:
        if self._recording:
            self.cancel()
        else:
            self._recording = True
            self.setText("Press keys…")
            self.setFocus(Qt.FocusReason.MouseFocusReason)

    def cancel(self) -> None:
        self._recording = False
        self._held_modifiers.clear()
        self._invalid_key = False
        self.setText("Record")

    def focusOutEvent(self, event: QFocusEvent) -> None:
        self.cancel()
        super().focusOutEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._recording:
            super().keyPressEvent(event)
            return
        if event.isAutoRepeat():
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.cancel()
        elif event.key() in _MODIFIER_KEYS:
            modifier = _modifier_token(event)
            assert modifier is not None
            self._held_modifiers[event.key()] = modifier
        else:
            token = _key_token(event.key())
            if token is None:
                self._invalid_key = True
                self.setText("Unsupported key")
            else:
                group_switch = bool(event.modifiers() & Qt.KeyboardModifier.GroupSwitchModifier)
                modifiers: list[str] = []
                for flag, key, fallback in _MODIFIERS:
                    if (
                        key == Qt.Key.Key_Control
                        and group_switch
                        and key not in self._held_modifiers
                    ):
                        continue
                    if key == Qt.Key.Key_Alt and group_switch:
                        modifiers.append(self._held_modifiers.get(Qt.Key.Key_AltGr, "right_alt"))
                    elif event.modifiers() & flag:
                        modifiers.append(self._held_modifiers.get(key, fallback))
                self.cancel()
                self.recorded.emit(
                    "key_combo" if modifiers else "key", "+".join([*modifiers, token])
                )
        event.accept()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if not self._recording:
            super().keyReleaseEvent(event)
            return
        token = self._held_modifiers.pop(event.key(), _modifier_token(event))
        if token is not None and not self._held_modifiers and not self._invalid_key:
            self.cancel()
            self.recorded.emit("key", token)
        event.accept()
