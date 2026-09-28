"""Fixture-backed physical control signatures for supported Naga layouts."""

from collections.abc import Mapping
from types import MappingProxyType

from naga_control.adapters.evdev.frames import EV_KEY, RawControlSignature
from naga_control.domain.profiles import LogicalControlId, PlateLayout, as_logical_control

_EMPTY_TRANSLATIONS: Mapping[RawControlSignature, LogicalControlId] = MappingProxyType({})


def _common(product_id: str) -> dict[RawControlSignature, LogicalControlId]:
    """Plate-independent controls, identical on both transports by capture."""
    return {
        RawControlSignature(product_id, "01", EV_KEY, 183, 458856): "dpi_up",
        RawControlSignature(product_id, "01", EV_KEY, 184, 458857): "dpi_down",
        RawControlSignature(product_id, "01", EV_KEY, 187, 458860): "ring_finger",
        RawControlSignature(product_id, "01", EV_KEY, 98, 458836): "top_front",
        RawControlSignature(product_id, "01", EV_KEY, 188, 458861): "top_rear",
        # Wheel tilt arrives without MSC_SCAN on the pointer interface.
        RawControlSignature(product_id, "00", EV_KEY, 185, None): "wheel_tilt_left",
        RawControlSignature(product_id, "00", EV_KEY, 186, None): "wheel_tilt_right",
    }


def _plate_12(product_id: str) -> dict[RawControlSignature, LogicalControlId]:
    """The sanitized 2026-09-27/28 12-button captures; identical on both transports."""
    translations = _common(product_id)
    for number in range(1, 11):
        signature = RawControlSignature(product_id, "02", EV_KEY, number + 1, 458781 + number)
        translations[signature] = as_logical_control(f"side_12_{number}")
    translations[RawControlSignature(product_id, "02", EV_KEY, 12, 458797)] = "side_12_11"
    translations[RawControlSignature(product_id, "02", EV_KEY, 13, 458798)] = "side_12_12"
    return translations


def _plate_6(product_id: str) -> dict[RawControlSignature, LogicalControlId]:
    """The sanitized 2026-09-28 HyperSpeed 6-button plate capture."""
    translations = _common(product_id)
    for number in range(1, 7):
        signature = RawControlSignature(product_id, "02", EV_KEY, number + 1, 458781 + number)
        translations[signature] = as_logical_control(f"side_6_{number}")
    return translations


def _plate_2(product_id: str) -> dict[RawControlSignature, LogicalControlId]:
    """The sanitized 2026-09-28 HyperSpeed 2-button plate capture."""
    translations = _common(product_id)
    translations[RawControlSignature(product_id, "00", EV_KEY, 276, 589829)] = "side_2_front"
    translations[RawControlSignature(product_id, "00", EV_KEY, 275, 589828)] = "side_2_rear"
    return translations


_WIRED_TRANSLATIONS: dict[int, Mapping[RawControlSignature, LogicalControlId]] = {
    12: MappingProxyType(_plate_12("00e7")),
}
_HYPER_SPEED_TRANSLATIONS: dict[int, Mapping[RawControlSignature, LogicalControlId]] = {
    12: MappingProxyType(_plate_12("00e8")),
    6: MappingProxyType(_plate_6("00e8")),
    2: MappingProxyType(_plate_2("00e8")),
}


def translations_for(
    product_id: str, plate_layout: PlateLayout
) -> Mapping[RawControlSignature, LogicalControlId]:
    """Return only controls backed by a sanitized capture for this transport and plate."""
    lowered = product_id.lower()
    if lowered == "00e8":
        return _HYPER_SPEED_TRANSLATIONS.get(plate_layout, _EMPTY_TRANSLATIONS)
    if lowered == "00e7":
        return _WIRED_TRANSLATIONS.get(plate_layout, _EMPTY_TRANSLATIONS)
    return _EMPTY_TRANSLATIONS
