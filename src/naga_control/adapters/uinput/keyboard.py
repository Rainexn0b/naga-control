"""Fixed virtual keyboard for verified Naga remapping output."""

from collections.abc import Mapping
from contextlib import suppress
from importlib import import_module
from typing import Protocol, cast

from naga_control.domain.actions import OUTPUT_KEY_TOKENS
from naga_control.domain.intents import KeyOutputIntent
from naga_control.ports.output import KeyboardOutput

VIRTUAL_KEYBOARD_NAME = "Naga Control Virtual Keyboard"
VIRTUAL_KEYBOARD_PHYS = "naga-control/virtual-keyboard"
VIRTUAL_VENDOR_ID = 0x4E43
VIRTUAL_PRODUCT_ID = 0x0001
VIRTUAL_VERSION = 0x0001


class UInputLike(Protocol):
    def write(self, event_type: int, code: int, value: int) -> None: ...

    def syn(self) -> None: ...

    def close(self) -> None: ...


class _Ecodes(Protocol):
    EV_KEY: int
    BUS_VIRTUAL: int


# The domain owns the output key vocabulary; this adapter only resolves it to codes.
KEY_TOKENS = tuple(sorted(OUTPUT_KEY_TOKENS))

_ECODES_ALIASES = {
    "left_alt": "KEY_LEFTALT",
    "right_alt": "KEY_RIGHTALT",
    "left_ctrl": "KEY_LEFTCTRL",
    "right_ctrl": "KEY_RIGHTCTRL",
    "left_shift": "KEY_LEFTSHIFT",
    "right_shift": "KEY_RIGHTSHIFT",
    "left_super": "KEY_LEFTMETA",
    "right_super": "KEY_RIGHTMETA",
    "escape": "KEY_ESC",
    "page_up": "KEY_PAGEUP",
    "page_down": "KEY_PAGEDOWN",
    "left_brace": "KEY_LEFTBRACE",
    "right_brace": "KEY_RIGHTBRACE",
}


def resolve_key_codes(ecodes: object) -> dict[str, int]:
    """Map every supported key token to its evdev code or fail closed."""
    codes: dict[str, int] = {}
    for token in KEY_TOKENS:
        name = _ECODES_ALIASES.get(token, f"KEY_{token.upper()}")
        value = getattr(ecodes, name, None)
        if not isinstance(value, int):
            raise RuntimeError(f"evdev does not provide {name}")
        codes[token] = value
    return codes


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


class VirtualKeyboard(KeyboardOutput):
    """Emit supported key intents and permanently fail closed after output errors."""

    def __init__(
        self, device: UInputLike, *, event_type: int, key_codes: Mapping[str, int]
    ) -> None:
        self._device = device
        self._event_type = event_type
        self._key_codes = dict(key_codes)
        self._held_codes: set[int] = set()
        self._closed = False

    def emit(self, intent: KeyOutputIntent) -> None:
        if self._closed:
            raise OSError("virtual keyboard is closed")
        if intent.value not in {0, 1, 2}:
            raise ValueError(f"unsupported key value {intent.value}")
        code = self._key_codes.get(intent.key)
        if code is None:
            raise ValueError(f"unsupported virtual keyboard key {intent.key!r}")
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


def create_virtual_keyboard() -> VirtualKeyboard:
    """Create the stable replacement keyboard only when service composition requests it."""
    evdev = import_module("evdev")
    ecodes = cast(_Ecodes, import_module("evdev.ecodes"))
    factory = cast(_UInputFactory, evdev.UInput)
    key_codes = resolve_key_codes(ecodes)
    device = factory(
        events={ecodes.EV_KEY: tuple(sorted(set(key_codes.values())))},
        name=VIRTUAL_KEYBOARD_NAME,
        phys=VIRTUAL_KEYBOARD_PHYS,
        bustype=ecodes.BUS_VIRTUAL,
        vendor=VIRTUAL_VENDOR_ID,
        product=VIRTUAL_PRODUCT_ID,
        version=VIRTUAL_VERSION,
    )
    return VirtualKeyboard(device, event_type=ecodes.EV_KEY, key_codes=key_codes)
