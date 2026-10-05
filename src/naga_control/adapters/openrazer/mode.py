"""Strict OpenRazer device-mode calls for the selected Naga client."""

from collections.abc import Callable
from typing import Protocol, cast

from naga_control.domain.hardware import DeviceMode, DeviceModeError

_MODES: dict[DeviceMode, tuple[str, int, int]] = {
    "software": ("3:0", 3, 0),
    "firmware": ("0:0", 0, 0),
}


class _Dbus(Protocol):
    def get_dbus_method(self, name: str, interface: str) -> object: ...


def _method(client: object, name: str) -> object:
    try:
        dbus = cast(_Dbus, object.__getattribute__(client, "_dbus"))
        method = dbus.get_dbus_method(name, "razer.device.misc")
    except AttributeError as exc:
        raise DeviceModeError("unsupported", f"OpenRazer lacks {name}.") from exc
    except Exception as exc:
        code = "read_failed" if name == "getDeviceMode" else "write_failed"
        raise DeviceModeError(code, f"Could not access OpenRazer {name}.") from exc
    if not callable(method):
        raise DeviceModeError("unsupported", f"OpenRazer lacks {name}.")
    return method


def _read(getter: object) -> DeviceMode:
    try:
        value = cast(Callable[[], object], getter)()
    except Exception as exc:
        raise DeviceModeError("read_failed", "Could not read OpenRazer device mode.") from exc
    for mode, (raw, _, _) in _MODES.items():
        if isinstance(value, str) and value == raw:
            return mode
    raise DeviceModeError("invalid_response", "OpenRazer returned an unknown device mode.")


def read_device_mode(client: object) -> DeviceMode:
    return _read(_method(client, "getDeviceMode"))


def set_device_mode(client: object, mode: DeviceMode) -> DeviceMode:
    if mode not in _MODES:
        raise ValueError("mode must be software or firmware")
    getter = _method(client, "getDeviceMode")
    if _read(getter) == mode:
        return mode
    setter = _method(client, "setDeviceMode")
    _, first, second = _MODES[mode]
    try:
        cast(Callable[[int, int], object], setter)(first, second)
    except Exception as exc:
        raise DeviceModeError("write_failed", "Could not set OpenRazer device mode.") from exc
    if _read(getter) != mode:
        raise DeviceModeError("mismatch", "OpenRazer device mode did not match the request.")
    return mode
