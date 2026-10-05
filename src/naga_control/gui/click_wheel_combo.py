"""Combo boxes that reserve wheel editing for an explicitly clicked editor."""

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QFocusEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QComboBox


class ClickWheelComboBox(QComboBox):
    """Let unarmed wheel events propagate to the surrounding scroll area."""

    def __init__(self) -> None:
        super().__init__()
        self._wheel_armed = False
        self._popup_open = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.installEventFilter(self)
        self.setToolTip("Click this editor before using the wheel to change its value.")

    def setEditable(self, editable: bool) -> None:
        super().setEditable(editable)
        editor = self.lineEdit()
        if editor is not None:
            editor.installEventFilter(self)

    def showPopup(self) -> None:
        self._popup_open = True
        super().showPopup()

    def hidePopup(self) -> None:
        super().hidePopup()
        self._popup_open = False
        if not self.hasFocus():
            self._wheel_armed = False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and isinstance(event, QMouseEvent)
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._wheel_armed = True
        elif (
            event.type() == QEvent.Type.FocusOut
            and isinstance(event, QFocusEvent)
            and event.reason() != Qt.FocusReason.PopupFocusReason
            and not self._popup_open
        ):
            self._wheel_armed = False
        return super().eventFilter(watched, event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._wheel_armed and self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()
