"""Fixed replacement-output creation and capability failures, without device access."""

import asyncio
from importlib import import_module
from types import SimpleNamespace
from typing import Literal

import pytest
from test_uinput_output_failures import Sink

from naga_control.adapters.uinput import keyboard, mouse, proxy


class Factory:
    def __init__(self, sink: Sink, error: BaseException | None = None) -> None:
        self.sink = sink
        self.error = error
        self.calls: list[dict[str, object]] = []

    def __call__(self, **kwargs: object) -> Sink:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.sink


def inject_uinput(monkeypatch: pytest.MonkeyPatch, factory: Factory) -> None:
    # Importing constants does not construct evdev descriptors or enumerate devices.
    modules = {
        "evdev": SimpleNamespace(UInput=factory),
        "evdev.ecodes": import_module("evdev.ecodes"),
    }
    for module in (keyboard, mouse, proxy):
        monkeypatch.setattr(module, "import_module", modules.__getitem__)


@pytest.mark.parametrize("kind", ["keyboard", "mouse"])
@pytest.mark.parametrize(
    "error_type", [OSError, RuntimeError, asyncio.CancelledError, KeyboardInterrupt]
)
def test_create_failure_propagates_without_inventing_owned_device(
    monkeypatch: pytest.MonkeyPatch,
    kind: Literal["keyboard", "mouse"],
    error_type: type[BaseException],
) -> None:
    sink = Sink()
    error = error_type("create failed")
    factory = Factory(sink, error)
    inject_uinput(monkeypatch, factory)

    with pytest.raises(error_type) as caught:
        if kind == "keyboard":
            keyboard.create_virtual_keyboard()
        else:
            mouse.create_virtual_mouse()

    assert caught.value is error
    assert len(factory.calls) == 1
    assert sink.calls == []  # Ownership never transferred out of the factory.


@pytest.mark.parametrize("missing", ["KEY_LEFTALT", "KEY_F12"])
@pytest.mark.parametrize("invalid", [None, "88", 88.0])
def test_bad_key_constant_prevents_uinput_creation(
    monkeypatch: pytest.MonkeyPatch, missing: str, invalid: object
) -> None:
    sink = Sink()
    factory = Factory(sink)
    inject_uinput(monkeypatch, factory)
    constants = SimpleNamespace(**vars(import_module("evdev.ecodes")))
    setattr(constants, missing, invalid)
    modules = {"evdev": SimpleNamespace(UInput=factory), "evdev.ecodes": constants}
    monkeypatch.setattr(keyboard, "import_module", modules.__getitem__)

    with pytest.raises(RuntimeError, match=missing):
        keyboard.create_virtual_keyboard()

    assert factory.calls == []
    assert sink.calls == []


def test_fixed_key_aliases_and_capabilities_use_linux_constants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = Sink()
    factory = Factory(sink)
    inject_uinput(monkeypatch, factory)
    codes = keyboard.resolve_key_codes(import_module("evdev.ecodes"))
    expected = {
        "left_alt": 56,
        "right_alt": 100,
        "left_ctrl": 29,
        "right_ctrl": 97,
        "left_shift": 42,
        "right_shift": 54,
        "left_super": 125,
        "right_super": 126,
        "escape": 1,
        "page_up": 104,
        "page_down": 109,
        "f12": 88,
    }
    assert {token: codes[token] for token in expected} == expected
    assert len(codes) == len(set(codes.values())) == 73
    output = keyboard.create_virtual_keyboard()
    assert factory.calls[0]["events"] == {1: tuple(sorted(codes.values()))}
    assert factory.calls[0]["bustype"] == 6
    assert factory.calls[0]["vendor"] == 0x4E43
    assert factory.calls[0]["product"] == 1
    output.close()
    assert sink.calls == ["close"]
