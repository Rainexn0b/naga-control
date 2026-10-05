"""Qt-free view models bound by widgets; no widget imports anything else."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast


@dataclass(frozen=True)
class ObservedView:
    """Optional observed hardware values published by the service."""

    dpi: tuple[int, int] | None = None
    active_dpi_stage: int | None = None
    scroll_mode: str | None = None
    scroll_acceleration: bool | None = None
    scroll_smart_reel: bool | None = None
    poll_rate: int | None = None
    battery_percent: float | None = None
    charging: bool | None = None
    firmware_version: str | None = None
    settings_failures: tuple[str, ...] = ()


@dataclass(frozen=True)
class ServiceSnapshotView:
    """Immutable parsed view of the service snapshot document."""

    status: str
    generation: int
    transport: str | None
    error: str | None
    calibrating: bool = False
    observed: ObservedView = ObservedView()
    desired_mode: str | None = None
    observed_mode: str | None = None
    mode_ready: bool = False
    mode_error: str | None = None


def parse_snapshot(document: str) -> ServiceSnapshotView:
    payload: dict[str, Any] = json.loads(document)
    raw_observed: dict[str, Any] = payload.get("observed") or {}
    observed = ObservedView(
        dpi=_optional_pair(raw_observed.get("dpi")),
        active_dpi_stage=_optional_int(raw_observed.get("active_dpi_stage")),
        scroll_mode=_optional_str(raw_observed.get("scroll_mode")),
        scroll_acceleration=_optional_bool(raw_observed.get("scroll_acceleration")),
        scroll_smart_reel=_optional_bool(raw_observed.get("scroll_smart_reel")),
        poll_rate=_optional_int(raw_observed.get("poll_rate")),
        battery_percent=_optional_float(raw_observed.get("battery_percent")),
        charging=_optional_bool(raw_observed.get("charging")),
        firmware_version=_optional_str(raw_observed.get("firmware_version")),
        settings_failures=tuple(str(item) for item in payload.get("settings_failures") or ()),
    )
    return ServiceSnapshotView(
        status=str(payload["status"]),
        generation=int(payload["generation"]),
        transport=_optional_str(payload.get("transport")),
        error=_optional_str(payload.get("error")),
        calibrating=payload.get("calibrating") is True,
        observed=observed,
        desired_mode=_optional_str(payload.get("desired_mode")),
        observed_mode=_optional_str(payload.get("observed_mode")),
        mode_ready=payload.get("mode_ready") is True,
        mode_error=_optional_str(payload.get("mode_error")),
    )


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _optional_pair(value: object) -> tuple[int, int] | None:
    if isinstance(value, list):
        items = cast("list[object]", value)
        if len(items) == 2:
            first, second = items
            if isinstance(first, int) and isinstance(second, int):
                return (first, second)
    return None


@dataclass(frozen=True)
class ConnectionState:
    """Service reachability as observed by the GUI."""

    reachable: bool
    detail: str | None = None


class ServiceModel:
    """Observable service state shared by all widgets of one GUI process."""

    def __init__(self) -> None:
        self.connection = ConnectionState(reachable=False)
        self.snapshot: ServiceSnapshotView | None = None
        self.configuration_revision: int | None = None
        self.configuration_document: str | None = None
        self.apply_status: str | None = None
        self._listeners: list[Callable[[], None]] = []

    def add_listener(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def _changed(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    def mark_reachable(self) -> None:
        if not self.connection.reachable:
            self.connection = ConnectionState(reachable=True)
            self._changed()

    def mark_unreachable(self, detail: str) -> None:
        replacement = ConnectionState(reachable=False, detail=detail)
        if self.connection != replacement:
            self.connection = replacement
            self._changed()

    def apply_snapshot(self, view: ServiceSnapshotView) -> None:
        changed = not self.connection.reachable or self.snapshot != view
        self.connection = ConnectionState(reachable=True)
        self.snapshot = view
        if changed:
            self._changed()

    def apply_configuration(self, revision: int, document: str) -> None:
        if self.configuration_revision is not None and revision < self.configuration_revision:
            return
        changed = self.configuration_revision != revision or self.configuration_document != document
        if changed:
            self.configuration_revision = revision
            self.configuration_document = document
            self._changed()

    def set_apply_status(self, status: str | None) -> None:
        if self.apply_status != status:
            self.apply_status = status
            self._changed()
