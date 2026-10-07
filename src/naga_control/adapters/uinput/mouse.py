"""Fixed virtual mouse for Naga button-mapping output."""

from collections.abc import Mapping
from contextlib import suppress
from importlib import import_module
from typing import Protocol, cast

from naga_control.domain.intents import MouseButtonOutputIntent
from naga_control.ports.output import MouseOutput

VIRTUAL_MOUSE_NAME = "Naga Control Virtual Mouse"
VIRTUAL_MOUSE_PHYS = "naga-control/virtual-mouse"
VIRTUAL_VENDOR_ID = 0x4E43
VIRTUAL_PRODUCT_ID = 0x0002
VIRTUAL_VERSION = 0x0001


class UInputLike(Protocol):
    def write(self, event_type: int, code: int, value: int) -> None: ...
    def syn(self) -> None: ...
    def close(self) -> None: ...


class _Ecodes(Protocol):
    EV_KEY: int
    BTN_LEFT: int
    BTN_RIGHT: int
    BTN_MIDDLE: int
    BTN_BACK: int
    BTN_FORWARD: int
    BUS_VIRTUAL: int


class _UInputFactory(Protocol):
    def __call__(
        self,
        *,
        events: Mapping[int, tuple[int, ...]],
        name: str,
        phys: str,
        bustype: int,
        vendor: int,
        product: int,
        version: int,
    ) -> UInputLike: ...


class VirtualMouse(MouseOutput):
    """Emit fixed mouse-button intents and fail closed after output errors."""

    def __init__(
        self, device: UInputLike, *, event_type: int, button_codes: Mapping[str, int]
    ) -> None:
        self._device = device
        self._event_type = event_type
        self._button_codes = dict(button_codes)
        self._held_codes: set[int] = set()
        self._closed = False

    def emit(self, intent: MouseButtonOutputIntent) -> None:
        if self._closed:
            raise OSError("virtual mouse is closed")
        code = self._button_codes.get(intent.button)
        if code is None:
            raise ValueError(f"unsupported virtual mouse button {intent.button!r}")
        if intent.value == 1:
            self._held_codes.add(code)
        try:
            self._device.write(self._event_type, code, intent.value)
            self._device.syn()
        except Exception:
            self._fail_closed()
            raise
        if intent.value == 0:
            self._held_codes.discard(code)

    def release_all(self) -> None:
        if self._closed:
            return
        first_error: Exception | None = None
        for code in tuple(self._held_codes):
            try:
                self._device.write(self._event_type, code, 0)
            except Exception as error:
                if first_error is None:
                    first_error = error
        if self._held_codes:
            try:
                self._device.syn()
            except Exception as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            self._fail_closed()
            raise first_error
        self._held_codes.clear()

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.release_all()
        finally:
            if not self._closed:
                self._closed = True
                self._device.close()

    def _fail_closed(self) -> None:
        try:
            for code in tuple(self._held_codes):
                with suppress(Exception):
                    self._device.write(self._event_type, code, 0)
            with suppress(Exception):
                self._device.syn()
        finally:
            self._held_codes.clear()
            self._closed = True
            with suppress(Exception):
                self._device.close()


def create_virtual_mouse() -> VirtualMouse:
    """Create the stable replacement mouse only when service composition requests it."""
    evdev = import_module("evdev")
    ecodes = cast(_Ecodes, import_module("evdev.ecodes"))
    factory = cast(_UInputFactory, evdev.UInput)
    button_codes = {
        "left": ecodes.BTN_LEFT,
        "right": ecodes.BTN_RIGHT,
        "middle": ecodes.BTN_MIDDLE,
        "back": ecodes.BTN_BACK,
        "forward": ecodes.BTN_FORWARD,
    }
    device = factory(
        events={ecodes.EV_KEY: tuple(button_codes.values())},
        name=VIRTUAL_MOUSE_NAME,
        phys=VIRTUAL_MOUSE_PHYS,
        bustype=ecodes.BUS_VIRTUAL,
        vendor=VIRTUAL_VENDOR_ID,
        product=VIRTUAL_PRODUCT_ID,
        version=VIRTUAL_VERSION,
    )
    return VirtualMouse(device, event_type=ecodes.EV_KEY, button_codes=button_codes)
