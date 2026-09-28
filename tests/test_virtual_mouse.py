from collections.abc import Mapping

import pytest

from naga_control.adapters.uinput import mouse
from naga_control.adapters.uinput.mouse import VirtualMouse
from naga_control.domain.intents import MouseButtonOutputIntent


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


def test_mouse_writes_framed_down_and_up() -> None:
    device = FakeUInput()
    output = _mouse(device)

    output.emit(MouseButtonOutputIntent("back", 1))
    output.emit(MouseButtonOutputIntent("back", 0))

    assert device.events == [(1, 278, 1), "syn", (1, 278, 0), "syn"]


def test_write_failure_releases_held_buttons_and_closes_the_device() -> None:
    device = FakeUInput()
    output = _mouse(device)
    output.emit(MouseButtonOutputIntent("back", 1))
    device.fail_write = True

    with pytest.raises(OSError, match="write failed"):
        output.emit(MouseButtonOutputIntent("back", 1))

    assert device.events[-3:] == [(1, 278, 1), (1, 278, 0), "syn"]
    assert device.closed


def test_mouse_rejects_unsupported_buttons_without_writing() -> None:
    device = FakeUInput()

    with pytest.raises(ValueError, match="unsupported"):
        VirtualMouse(device, event_type=1, button_codes={}).emit(MouseButtonOutputIntent("back", 1))

    assert device.events == []


def test_factory_creates_a_fixed_non_razer_virtual_mouse(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[dict[str, object]] = []

    class FakeFactory:
        def __call__(self, **kwargs: object) -> FakeUInput:
            created.append(kwargs)
            return FakeUInput()

    class FakeEcodes:
        EV_KEY = 1
        BTN_LEFT = 272
        BTN_RIGHT = 273
        BTN_MIDDLE = 274
        BTN_BACK = 278
        BTN_FORWARD = 279
        BUS_VIRTUAL = 6

    modules: Mapping[str, object] = {
        "evdev": type("FakeEvdev", (), {"UInput": FakeFactory()})(),
        "evdev.ecodes": FakeEcodes(),
    }
    monkeypatch.setattr(mouse, "import_module", modules.__getitem__)

    output = mouse.create_virtual_mouse()

    assert isinstance(output, VirtualMouse)
    assert created == [
        {
            "events": {1: (272, 273, 274, 278, 279)},
            "name": "Naga Control Virtual Mouse",
            "phys": "naga-control/virtual-mouse",
            "bustype": 6,
            "vendor": 0x4E43,
            "product": 2,
            "version": 1,
        }
    ]


def _mouse(device: FakeUInput) -> VirtualMouse:
    return VirtualMouse(device, event_type=1, button_codes={"back": 278})
