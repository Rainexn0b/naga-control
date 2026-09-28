"""Strict validation of OpenRazer capability property values."""

from typing import cast

from naga_control.domain.hardware import (
    HardwareDpiStage,
    HardwareScrollMode,
    HardwareState,
    HardwareTransport,
)

SCROLL_MODES: tuple[HardwareScrollMode, ...] = (
    "tactile",
    "free_spin",
    "precision_tactile",
)


class MissingCapabilityError(Exception):
    pass


class InvalidCapabilityResponseError(Exception):
    pass


def read_hardware_state(
    client: object, generation: int, transport: HardwareTransport
) -> HardwareState:
    dpi = _read_dpi(client)
    active, stages = read_dpi_stages(client)
    max_dpi = _read_max_dpi(client)
    mode, options = read_scroll_modes(client)
    acceleration = _read_bool(client, "scroll_acceleration")
    smart_reel = _read_bool(client, "scroll_smart_reel")
    return HardwareState(
        status="available",
        generation=generation,
        transport=transport,
        dpi=dpi,
        dpi_stages=stages,
        active_dpi_stage=active,
        max_dpi=max_dpi,
        scroll_mode=mode,
        scroll_mode_options=options,
        scroll_acceleration=acceleration,
        scroll_smart_reel=smart_reel,
        poll_rate=_optional_int(client, "poll_rate"),
        battery_percent=_optional_battery(client),
        charging=_optional_bool(client, "is_charging"),
        firmware_version=_optional_firmware(client),
    )


def read_dpi_stages(client: object) -> tuple[int, tuple[HardwareDpiStage, ...]]:
    stage_data = _sequence(_property(client, "dpi_stages"))
    if len(stage_data) != 2:
        raise InvalidCapabilityResponseError
    active, raw_stages = stage_data
    if type(active) is not int:
        raise InvalidCapabilityResponseError
    stages = tuple(_pair(stage) for stage in _sequence(raw_stages))
    if not 1 <= len(stages) <= 5 or not 1 <= active <= len(stages):
        raise InvalidCapabilityResponseError
    return active, stages


def read_scroll_modes(client: object) -> tuple[HardwareScrollMode, tuple[HardwareScrollMode, ...]]:
    mode = _scroll_mode(_property(client, "scroll_mode"))
    options: tuple[HardwareScrollMode, ...] = tuple(
        _scroll_mode(option) for option in _sequence(_property(client, "scroll_mode_options"))
    )
    if not options or len(set(options)) != len(options) or mode not in options:
        raise InvalidCapabilityResponseError
    return mode, options


def _read_dpi(client: object) -> HardwareDpiStage:
    return _pair(_property(client, "dpi"))


def _read_max_dpi(client: object) -> int:
    value = _property(client, "max_dpi")
    if type(value) is not int or not 100 <= value <= 50000:
        raise InvalidCapabilityResponseError
    return value


def _read_bool(client: object, name: str) -> bool:
    value = _property(client, name)
    if type(value) is not bool:
        raise InvalidCapabilityResponseError
    return value


def _property(client: object, name: str) -> object:
    try:
        return getattr(client, name)
    except AttributeError as exc:
        raise MissingCapabilityError from exc


def _optional_int(client: object, name: str) -> int | None:
    try:
        value = _property(client, name)
    except Exception:
        return None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_bool(client: object, name: str) -> bool | None:
    try:
        value = _property(client, name)
    except Exception:
        return None
    return value if isinstance(value, bool) else None


def _optional_battery(client: object) -> float | None:
    try:
        value = _property(client, "battery_level")
    except Exception:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if 0.0 <= float(value) <= 100.0 else None


def _optional_firmware(client: object) -> str | None:
    try:
        value = _property(client, "firmware_version")
    except Exception:
        return None
    return value if isinstance(value, str) and value.strip() else None


def _pair(value: object) -> HardwareDpiStage:
    pair = _sequence(value)
    if len(pair) != 2:
        raise InvalidCapabilityResponseError
    x, y = pair
    if type(x) is not int or type(y) is not int:
        raise InvalidCapabilityResponseError
    try:
        return HardwareDpiStage(x, y)
    except ValueError as exc:
        raise InvalidCapabilityResponseError from exc


def _scroll_mode(value: object) -> HardwareScrollMode:
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < len(SCROLL_MODES):
        return SCROLL_MODES[value]
    if value not in SCROLL_MODES:
        raise InvalidCapabilityResponseError
    return value


def _sequence(value: object) -> tuple[object, ...] | list[object]:
    if type(value) is tuple:
        return cast(tuple[object, ...], value)
    if type(value) is list:
        return cast(list[object], value)
    raise InvalidCapabilityResponseError
