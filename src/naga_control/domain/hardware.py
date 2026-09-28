"""Immutable observed hardware state without adapter-specific identity data."""

from dataclasses import dataclass
from typing import Literal

type HardwareTransport = Literal["wired", "hyperspeed"]
type HardwareStatus = Literal[
    "absent",
    "available",
    "unavailable",
    "unsupported",
    "transport_conflict",
    "multiple_device_conflict",
]
type HardwareIssueCode = Literal[
    "input_nodes_unavailable",
    "transport_conflict",
    "multiple_device_conflict",
    "prerequisite_unavailable",
    "backend_unavailable",
    "device_unavailable",
    "unsupported_capability",
    "invalid_response",
    "matching_device_not_found",
    "ambiguous_matching_device",
]
type HardwareScrollMode = Literal["tactile", "free_spin", "precision_tactile"]


@dataclass(frozen=True, slots=True)
class HardwareIssue:
    """A stable, displayable reason that hardware is not controllable."""

    code: HardwareIssueCode
    message: str


@dataclass(frozen=True, slots=True)
class SettingsFailure:
    """One desired setting that could not be applied to the hardware."""

    setting: str
    message: str


@dataclass(frozen=True, slots=True)
class HardwareDpiStage:
    """One observed X/Y DPI stage."""

    x: int
    y: int

    def __post_init__(self) -> None:
        _validate_dpi(self.x)
        _validate_dpi(self.y)


@dataclass(frozen=True, slots=True)
class HardwareState:
    """An observed snapshot safe to expose outside the hardware adapter."""

    status: HardwareStatus
    generation: int
    transport: HardwareTransport | None = None
    error: HardwareIssue | None = None
    dpi: HardwareDpiStage | None = None
    dpi_stages: tuple[HardwareDpiStage, ...] = ()
    active_dpi_stage: int | None = None
    max_dpi: int | None = None
    scroll_mode: HardwareScrollMode | None = None
    scroll_mode_options: tuple[HardwareScrollMode, ...] = ()
    scroll_acceleration: bool | None = None
    scroll_smart_reel: bool | None = None
    poll_rate: int | None = None
    battery_percent: float | None = None
    charging: bool | None = None
    firmware_version: str | None = None

    def __post_init__(self) -> None:
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("generation must be a non-negative integer")
        object.__setattr__(self, "dpi_stages", tuple(self.dpi_stages))
        object.__setattr__(self, "scroll_mode_options", tuple(self.scroll_mode_options))
        if self.status == "available":
            _validate_available_state(self)
        elif (
            any(
                value is not None
                for value in (
                    self.dpi,
                    self.active_dpi_stage,
                    self.max_dpi,
                    self.scroll_mode,
                    self.scroll_acceleration,
                    self.scroll_smart_reel,
                )
            )
            or self.dpi_stages
            or self.scroll_mode_options
        ):
            raise ValueError("unavailable hardware states cannot retain observed device values")


def _validate_available_state(state: HardwareState) -> None:
    if state.transport is None or state.error is not None:
        raise ValueError("available hardware state requires a transport and no error")
    if state.dpi is None or state.max_dpi is None or state.active_dpi_stage is None:
        raise ValueError("available hardware state requires DPI values")
    if state.scroll_mode is None:
        raise ValueError("available hardware state requires a scroll mode")
    if type(state.max_dpi) is not int or not 100 <= state.max_dpi <= 50000:
        raise ValueError("max_dpi must be an integer from 100 through 50000")
    if not 1 <= len(state.dpi_stages) <= 5:
        raise ValueError("dpi_stages must contain from 1 through 5 stages")
    if not 1 <= state.active_dpi_stage <= len(state.dpi_stages):
        raise ValueError("active_dpi_stage must select an observed DPI stage")
    if not state.scroll_mode_options or state.scroll_mode not in state.scroll_mode_options:
        raise ValueError("scroll_mode must be one of the observed options")
    if len(set(state.scroll_mode_options)) != len(state.scroll_mode_options):
        raise ValueError("scroll_mode_options must not contain duplicates")
    if type(state.scroll_acceleration) is not bool or type(state.scroll_smart_reel) is not bool:
        raise ValueError("scroll feature values must be booleans")


def _validate_dpi(value: int) -> None:
    if type(value) is not int or not 100 <= value <= 50000:
        raise ValueError("DPI must be an integer from 100 through 50000")
