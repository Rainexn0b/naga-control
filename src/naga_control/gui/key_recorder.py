"""Focused keyboard shortcut capture for the binding editor."""

from typing import cast

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QFocusEvent, QKeyEvent
from PySide6.QtWidgets import QApplication, QPushButton

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
# Qt reports shifted digit-row keys by their level-2 symbol on Latin layouts
# (e.g. Ctrl+Shift+8 arrives as Key_Asterisk, not Key_8). Map only symbols
# whose base key is in the supported output vocabulary; all other symbols stay
# unsupported so the recorder fails closed. Applied only when Shift is held.
_SHIFTED_SYMBOLS: dict[int, str] = {
    Qt.Key.Key_Exclam: "1",
    Qt.Key.Key_At: "2",
    Qt.Key.Key_NumberSign: "3",
    Qt.Key.Key_Dollar: "4",
    Qt.Key.Key_Percent: "5",
    Qt.Key.Key_AsciiCircum: "6",
    Qt.Key.Key_Ampersand: "7",
    Qt.Key.Key_Asterisk: "8",
    Qt.Key.Key_ParenLeft: "9",
    Qt.Key.Key_ParenRight: "0",
    Qt.Key.Key_Underscore: "minus",
    Qt.Key.Key_Plus: "equal",
}
# Keypad keys keep their own identity: consulted only when the KeypadModifier
# flag is set, before the plain _key_token lookup, so keypad digits/operators
# never collapse onto main-row tokens.
_KEYPAD_KEYS: dict[int, str] = {
    Qt.Key.Key_Plus: "kp_plus",
    Qt.Key.Key_Minus: "kp_minus",
    Qt.Key.Key_Asterisk: "kp_asterisk",
    Qt.Key.Key_Slash: "kp_slash",
    Qt.Key.Key_Enter: "kp_enter",
    Qt.Key.Key_Period: "kp_dot",
    Qt.Key.Key_0: "kp_0",
    Qt.Key.Key_1: "kp_1",
    Qt.Key.Key_2: "kp_2",
    Qt.Key.Key_3: "kp_3",
    Qt.Key.Key_4: "kp_4",
    Qt.Key.Key_5: "kp_5",
    Qt.Key.Key_6: "kp_6",
    Qt.Key.Key_7: "kp_7",
    Qt.Key.Key_8: "kp_8",
    Qt.Key.Key_9: "kp_9",
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
        self._filter_installed = False
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
            # Application event filters run inside notify_helper before the
            # target object (including QWidgetWindow) processes the event, so
            # consuming Backtab here stops Qt focus traversal from stealing
            # the chord. A keyboard grab cannot do that: traversal pre-empts
            # both the focus widget and the grabber.
            app = QApplication.instance()
            if app is not None:
                app.installEventFilter(self)
                self._filter_installed = True

    def cancel(self) -> None:
        if self._filter_installed:
            app = QApplication.instance()
            if app is not None:
                app.removeEventFilter(self)
            self._filter_installed = False
        self._recording = False
        self._held_modifiers.clear()
        self._invalid_key = False
        self.setText("Record")

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if not self._recording:
            return False
        event_type = event.type()
        if event_type == QEvent.Type.KeyPress:
            self._handle_key_press(cast(QKeyEvent, event))
            return True
        if event_type == QEvent.Type.KeyRelease:
            self._handle_key_release(cast(QKeyEvent, event))
            return True
        return False

    def focusOutEvent(self, event: QFocusEvent) -> None:
        self.cancel()
        super().focusOutEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._recording:
            super().keyPressEvent(event)
            return
        self._handle_key_press(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if not self._recording:
            super().keyReleaseEvent(event)
            return
        self._handle_key_release(event)

    def _handle_key_press(self, event: QKeyEvent) -> None:
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
            token: str | None = None
            if event.modifiers() & Qt.KeyboardModifier.KeypadModifier:
                token = _KEYPAD_KEYS.get(event.key())
            if token is None:
                token = _key_token(event.key())
            if token is None and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                token = _SHIFTED_SYMBOLS.get(event.key())
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

    def _handle_key_release(self, event: QKeyEvent) -> None:
        token = self._held_modifiers.pop(event.key(), _modifier_token(event))
        if token is not None and not self._held_modifiers and not self._invalid_key:
            self.cancel()
            self.recorded.emit("key", token)
        event.accept()
