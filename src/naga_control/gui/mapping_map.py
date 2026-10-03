"""Interactive mapping illustration with clickable control zones."""

from pathlib import Path
from typing import Any

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsScene,
    QGraphicsView,
)

from naga_control.domain.actions import Action
from naga_control.gui.actions_view import action_kind, format_action_detail
from naga_control.gui.mapping_zones import MappingZone, all_zones

_ACCENT = QColor(68, 255, 136)
_DISABLED = QColor(128, 128, 128)
_SELECT_WIDTH = 3.0


def mapping_image_path() -> Path:
    """Return the bundled mapping illustration path."""
    return Path(__file__).resolve().parent / "assets" / "Mapping.preview.png"


class _ZoneItem(QGraphicsPolygonItem):
    """One hotspot rectangle with hover and click handling."""

    def __init__(self, zone: MappingZone, parent_map: "MappingMapView") -> None:
        super().__init__()
        self.zone = zone
        self._parent_map = parent_map
        self._enabled = False
        self._selected = False
        self.setAcceptHoverEvents(True)
        self.setToolTip(zone.label)
        self._refresh_style(hovered=False)

    def set_zone_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.setCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor)
        self._refresh_style(hovered=False)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._refresh_style(hovered=False)

    def hoverEnterEvent(self, event: Any) -> None:
        self._refresh_style(hovered=True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: Any) -> None:
        self._refresh_style(hovered=False)
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event: Any) -> None:
        if self._enabled:
            self._parent_map.zone_clicked(self.zone)
        super().mousePressEvent(event)

    def _refresh_style(self, hovered: bool) -> None:
        if self._selected:
            self.setPen(QPen(_ACCENT, _SELECT_WIDTH))
        elif self._enabled:
            self.setPen(QPen(Qt.PenStyle.NoPen))
        else:
            self.setPen(QPen(_DISABLED, 1, Qt.PenStyle.DotLine))
        if hovered and self._enabled:
            self.setBrush(QBrush(QColor(_ACCENT.red(), _ACCENT.green(), _ACCENT.blue(), 90)))
        elif not self._enabled:
            self.setBrush(QBrush(QColor(0, 0, 0, 60)))
        else:
            self.setBrush(QBrush(Qt.BrushStyle.NoBrush))


class MappingMapView(QGraphicsView):
    """Scalable view of the mapping illustration."""

    zone_selected = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.pixmap_item = QGraphicsPixmapItem(QPixmap(str(mapping_image_path())))
        self.scene().addItem(self.pixmap_item)
        self._plate_layout = 12
        self._actions_cache: dict[str, Action | None] = {}
        self.zone_items: list[_ZoneItem] = []
        for zone in all_zones():
            item = _ZoneItem(zone, self)
            width = self.pixmap_item.pixmap().width()
            height = self.pixmap_item.pixmap().height()
            item.setPolygon(QPolygonF([QPointF(x * width, y * height) for x, y in zone.polygon]))
            self.scene().addItem(item)
            self.zone_items.append(item)
        self._apply_availability()
        self.setMinimumHeight(280)

    def zone_clicked(self, zone: MappingZone) -> None:
        if zone.control_id is not None:
            self.set_selected(zone.control_id)
            self.zone_selected.emit(zone.control_id)

    def set_plate_layout(self, plate_layout: int) -> None:
        if plate_layout == self._plate_layout:
            return
        self._plate_layout = plate_layout
        self._apply_availability()

    def set_actions(self, actions: dict[str, Action | None]) -> None:
        self._actions_cache = dict(actions)
        for item in self.zone_items:
            control = item.zone.control_id
            if control is None:
                hint = item.zone.hint or "decorative"
                item.setToolTip(f"{item.zone.label} — {hint}")
            else:
                action = actions.get(control)
                if action is None:
                    item.setToolTip(f"{item.zone.label} — passthrough")
                else:
                    item.setToolTip(
                        f"{item.zone.label} — {action_kind(action)}: {format_action_detail(action)}"
                    )

    def set_selected(self, control_id: str | None) -> None:
        for item in self.zone_items:
            item.set_selected(item.zone.control_id == control_id)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _apply_availability(self) -> None:
        for item in self.zone_items:
            active = item.zone.plate is None or item.zone.plate == self._plate_layout
            item.set_zone_enabled(item.zone.control_id is not None)
            item.setOpacity(1.0 if active else 0.55)
        self.set_actions(self._actions_cache)
