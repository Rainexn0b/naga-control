from collections.abc import Mapping
from typing import cast

import pytest

from naga_control.adapters.uinput import keyboard
from naga_control.adapters.uinput.keyboard import VirtualKeyboard
from naga_control.domain.intents import KeyOutputIntent


class FakeUInput:
    def __init__(self, *, fail_write: bool = False, fail_syn: bool = False) -> None:
        self.events: list[tuple[int, int, int] | str] = []
        self.fail_write = fail_write
        self.fail_syn = fail_syn
        self.closed = False

    def write(self, event_type: int, code: int, value: int) -> None:
        self.events.append((event_type, code, value))
        if self.fail_write:
            self.fail_write = False
            raise OSError("write failed")

    def syn(self) -> None:
        self.events.append("syn")
        if self.fail_syn:
            self.fail_syn = False
            raise OSError("sync failed")

    def close(self) -> None:
        self.closed = True


def test_keyboard_writes_framed_down_repeat_and_up() -> None:
    device = FakeUInput()
    output = _keyboard(device)

    output.emit(KeyOutputIntent("left_alt", 1))
    output.emit(KeyOutputIntent("left_alt", 2))
    output.emit(KeyOutputIntent("left_alt", 0))

    assert device.events == [(1, 56, 1), "syn", (1, 56, 2), "syn", (1, 56, 0), "syn"]


def test_write_failure_releases_held_keys_and_closes_the_device() -> None:
    device = FakeUInput()
    output = _keyboard(device)
    output.emit(KeyOutputIntent("left_alt", 1))
    device.fail_write = True

    with pytest.raises(OSError, match="write failed"):
        output.emit(KeyOutputIntent("left_alt", 2))

    assert device.events[-3:] == [(1, 56, 2), (1, 56, 0), "syn"]
    assert device.closed


def test_sync_failure_releases_the_key_that_was_queued_before_the_failure() -> None:
    device = FakeUInput(fail_syn=True)
    output = _keyboard(device)

    with pytest.raises(OSError, match="sync failed"):
        output.emit(KeyOutputIntent("left_alt", 1))

    assert device.events == [(1, 56, 1), "syn", (1, 56, 0), "syn"]
    assert device.closed


def test_keyboard_rejects_unsupported_keys_without_writing() -> None:
    device = FakeUInput()

    with pytest.raises(ValueError, match="unsupported"):
        _keyboard(device).emit(KeyOutputIntent("f", 1))

    assert device.events == []


def test_factory_creates_a_fixed_non_razer_virtual_keyboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[dict[str, object]] = []
    codes: dict[str, int] = {}

    class FakeFactory:
        def __call__(self, **kwargs: object) -> FakeUInput:
            created.append(kwargs)
            return FakeUInput()

    class FakeEcodes:
        EV_KEY = 1
        BUS_VIRTUAL = 6

        def __getattr__(self, name: str) -> int:
            if not name.startswith("KEY_"):
                raise AttributeError(name)
            code = codes.get(name)
            if code is None:
                code = 100 + len(codes)
                codes[name] = code
            return code

    modules: Mapping[str, object] = {
        "evdev": type("FakeEvdev", (), {"UInput": FakeFactory()})(),
        "evdev.ecodes": FakeEcodes(),
    }
    monkeypatch.setattr(keyboard, "import_module", modules.__getitem__)

    output = keyboard.create_virtual_keyboard()

    assert isinstance(output, VirtualKeyboard)
    assert len(created) == 1
    events = cast("dict[int, tuple[int, ...]]", created[0]["events"])
    assert set(events) == {1}
    assert set(events[1]) == set(codes.values())
    assert created[0]["name"] == "Naga Control Virtual Keyboard"
    assert created[0]["phys"] == "naga-control/virtual-keyboard"
    assert created[0]["bustype"] == 6
    assert created[0]["vendor"] == 0x4E43
    assert created[0]["product"] == 1
    assert created[0]["version"] == 1


def test_key_tokens_cover_default_bindings_and_modifiers() -> None:
    required = {"minus", "equal", *(str(digit) for digit in range(1, 10)), "0"}
    assert required <= set(keyboard.KEY_TOKENS)
    assert {"left_alt", "left_ctrl", "left_super"} <= set(keyboard.KEY_TOKENS)


def test_resolve_key_codes_fails_closed_for_a_missing_ecode() -> None:
    class EmptyEcodes:
        EV_KEY = 1
        BUS_VIRTUAL = 6

    with pytest.raises(RuntimeError, match="KEY_LEFTALT"):
        keyboard.resolve_key_codes(EmptyEcodes())


def _keyboard(device: FakeUInput) -> VirtualKeyboard:
    return VirtualKeyboard(device, event_type=1, key_codes={"left_alt": 56})
