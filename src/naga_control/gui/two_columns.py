"""Native scrollable columns that stack when their viewport becomes narrow."""

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QGridLayout, QScrollArea, QWidget


class TwoColumns(QScrollArea):
    """Keep two top-aligned columns readable at desktop and narrow widths."""

    def __init__(self, left: QWidget, right: QWidget) -> None:
        super().__init__()
        self._left = left
        self._right = right
        self.is_stacked = False
        contents = QWidget()
        self.columns_layout = QGridLayout(contents)
        self.columns_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.columns_layout.addWidget(left, 0, 0, Qt.AlignmentFlag.AlignTop)
        self.columns_layout.addWidget(right, 0, 1, Qt.AlignmentFlag.AlignTop)
        self.columns_layout.setColumnStretch(0, 1)
        self.columns_layout.setColumnStretch(1, 1)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setWidget(contents)
        self.viewport().installEventFilter(self)
        self._arrange()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.viewport() and event.type() == QEvent.Type.Resize:
            self._arrange()
        return super().eventFilter(watched, event)

    def _arrange(self) -> None:
        stacked = self.viewport().width() < 850
        if stacked == self.is_stacked:
            return
        self.is_stacked = stacked
        self.columns_layout.removeWidget(self._left)
        self.columns_layout.removeWidget(self._right)
        self.columns_layout.addWidget(self._left, 0, 0, Qt.AlignmentFlag.AlignTop)
        self.columns_layout.addWidget(
            self._right, 1 if stacked else 0, 0 if stacked else 1, Qt.AlignmentFlag.AlignTop
        )
        self.columns_layout.setColumnStretch(1, 0 if stacked else 1)
