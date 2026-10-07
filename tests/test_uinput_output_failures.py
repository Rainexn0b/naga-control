"""Fake-only uinput failure contracts; physical grab ownership is tested elsewhere."""

from dataclasses import replace
from typing import Literal

import pytest

from naga_control.adapters.uinput import keyboard, mouse
from naga_control.domain.actions import KeyAction, KeyComboAction, MouseButtonAction
from naga_control.domain.defaults import default_configuration
from naga_control.domain.intents import KeyOutputIntent, MouseButtonOutputIntent
from naga_control.domain.profiles import Binding, as_logical_control
from naga_control.service.action_dispatcher import ActionDispatcher

type Kind = Literal["keyboard", "mouse"]
type Call = tuple[int, int, int] | str


class Sink:
    def __init__(self) -> None:
        self.calls: list[Call] = []
        self.write_errors: list[BaseException | None] = []
        self.syn_errors: list[BaseException | None] = []
        self.close_errors: list[BaseException | None] = []

    def write(self, event_type: int, code: int, value: int) -> None:
        self.calls.append((event_type, code, value))
        self._raise_next(self.write_errors)

    def syn(self) -> None:
        self.calls.append("syn")
        self._raise_next(self.syn_errors)

    def close(self) -> None:
        self.calls.append("close")
        self._raise_next(self.close_errors)

    @staticmethod
    def _raise_next(errors: list[BaseException | None]) -> None:
        if errors and (error := errors.pop(0)) is not None:
            raise error


def _output(kind: Kind, sink: Sink) -> keyboard.VirtualKeyboard | mouse.VirtualMouse:
    if kind == "keyboard":
        return keyboard.VirtualKeyboard(
            sink, event_type=1, key_codes={"left_alt": 56, "left_ctrl": 29, "f": 33}
        )
    return mouse.VirtualMouse(sink, event_type=1, button_codes={"back": 278, "forward": 279})


def _emit(output: keyboard.VirtualKeyboard | mouse.VirtualMouse, value: Literal[0, 1]) -> None:
    if isinstance(output, keyboard.VirtualKeyboard):
        output.emit(KeyOutputIntent("left_alt", value))
    else:
        output.emit(MouseButtonOutputIntent("back", value))


def _hold_two(output: keyboard.VirtualKeyboard | mouse.VirtualMouse) -> set[int]:
    _emit(output, 1)
    if isinstance(output, keyboard.VirtualKeyboard):
        output.emit(KeyOutputIntent("left_ctrl", 1))
        return {56, 29}
    output.emit(MouseButtonOutputIntent("forward", 1))
    return {278, 279}


@pytest.mark.parametrize("kind", ["keyboard", "mouse"])
@pytest.mark.parametrize("value", [0, 1])
@pytest.mark.parametrize("phase", ["write", "syn"])
@pytest.mark.parametrize("error_type", [OSError, RuntimeError])
def test_emit_failure_propagates_and_attempts_release_before_closing(
    kind: Kind, value: Literal[0, 1], phase: str, error_type: type[Exception]
) -> None:
    sink = Sink()
    output = _output(kind, sink)
    _emit(output, 1)
    sink.calls.clear()
    error = error_type("output failed")
    if phase == "write":
        sink.write_errors = [error]
    else:
        sink.syn_errors = [error]

    with pytest.raises(error_type) as caught:
        _emit(output, value)

    assert caught.value is error  # The reader/consumer owner must receive the failure.
    code = 56 if kind == "keyboard" else 278
    attempted: list[Call] = [(1, code, value)]
    if phase == "syn":
        attempted.append("syn")
    assert sink.calls == [*attempted, (1, code, 0), "syn", "close"]
    before = sink.calls.copy()
    with pytest.raises(OSError, match="closed"):
        _emit(output, 1)
    output.release_all()
    output.close()
    assert sink.calls == before


@pytest.mark.parametrize("kind", ["keyboard", "mouse"])
@pytest.mark.parametrize("phase", ["write", "syn"])
@pytest.mark.parametrize("error_type", [OSError, RuntimeError])
def test_emit_retains_primary_despite_every_secondary_cleanup_operation_failing(
    kind: Kind, phase: str, error_type: type[Exception]
) -> None:
    sink = Sink()
    output = _output(kind, sink)
    held = _hold_two(output)
    sink.calls.clear()
    error = error_type("primary output failure")
    sink.write_errors = [
        error if phase == "write" else None,
        RuntimeError("first cleanup release failed"),
        RuntimeError("second cleanup release failed"),
    ]
    sink.syn_errors = [RuntimeError("cleanup sync failed")]
    if phase == "syn":
        sink.syn_errors.insert(0, error)
    sink.close_errors = [RuntimeError("cleanup close failed")]

    with pytest.raises(error_type) as caught:
        _emit(output, 0)

    assert caught.value is error
    assert {call[1] for call in sink.calls if isinstance(call, tuple) and call[2] == 0} == held
    assert sink.calls.count("syn") == (2 if phase == "syn" else 1)
    assert sink.calls[-1] == "close" and sink.calls.count("close") == 1
    before = sink.calls.copy()
    with pytest.raises(OSError, match="closed"):
        _emit(output, 1)
    output.close()
    assert sink.calls == before


@pytest.mark.parametrize("kind", ["keyboard", "mouse"])
def test_successful_release_all_clears_holds_without_releasing_them_again(kind: Kind) -> None:
    sink = Sink()
    output = _output(kind, sink)
    held = _hold_two(output)
    sink.calls.clear()
    output.release_all()
    assert {call for call in sink.calls if isinstance(call, tuple)} == {
        (1, code, 0) for code in held
    }
    assert len(sink.calls) == 3 and sink.calls[-1] == "syn"
    before = sink.calls.copy()
    output.release_all()
    assert sink.calls == before
    output.close()
    assert sink.calls == [*before, "close"]


@pytest.mark.parametrize("kind", ["keyboard", "mouse"])
@pytest.mark.parametrize("operation", ["release_all", "close"])
@pytest.mark.parametrize("phase", ["write", "syn"])
@pytest.mark.parametrize(
    "error_type,secondary_type",
    [(OSError, OSError), (OSError, RuntimeError), (RuntimeError, RuntimeError)],
)
def test_cleanup_attempts_every_held_release_and_sync_then_propagates_first(
    kind: Kind,
    operation: str,
    phase: str,
    error_type: type[Exception],
    secondary_type: type[Exception],
) -> None:
    sink = Sink()
    output = _output(kind, sink)
    held = _hold_two(output)
    sink.calls.clear()
    error = error_type("first cleanup failure")
    if phase == "write":
        sink.write_errors = [error, secondary_type("second release failed")]
        sink.syn_errors = [RuntimeError("secondary sync failure")]
    else:
        sink.syn_errors = [error]
    sink.close_errors = [RuntimeError("secondary close failure")]

    with pytest.raises(error_type) as caught:
        getattr(output, operation)()

    assert caught.value is error
    releases = {call[1] for call in sink.calls if isinstance(call, tuple) and call[2] == 0}
    assert releases == held
    assert "syn" in sink.calls
    assert sink.calls[-1] == "close" and sink.calls.count("close") == 1
    before = sink.calls.copy()
    with pytest.raises(OSError, match="closed"):
        _emit(output, 1)
    output.release_all()
    output.close()
    assert sink.calls == before


@pytest.mark.parametrize("kind", ["keyboard", "mouse"])
@pytest.mark.parametrize("release_type", [None, OSError, RuntimeError])
@pytest.mark.parametrize("close_type", [OSError, RuntimeError])
def test_close_attempts_sink_close_once_and_retains_first_cleanup_error(
    kind: Kind, release_type: type[Exception] | None, close_type: type[Exception]
) -> None:
    sink = Sink()
    output = _output(kind, sink)
    held = _hold_two(output)
    sink.calls.clear()
    close_error = close_type("close failed")
    sink.close_errors = [close_error]
    first = close_error
    if release_type is not None:
        first = release_type("release sync failed")
        sink.syn_errors = [first]

    with pytest.raises(type(first)) as caught:
        output.close()

    assert caught.value is first
    assert {call[1] for call in sink.calls if isinstance(call, tuple)} == held
    assert sink.calls.count("close") == 1
    before = sink.calls.copy()
    output.close()
    assert sink.calls == before


@pytest.mark.parametrize("kind", ["keyboard", "mouse"])
def test_refcounts_preserve_shared_hold_and_propagate_final_release_failure(kind: Kind) -> None:
    action = KeyAction("left_alt") if kind == "keyboard" else MouseButtonAction("back")
    profile = default_configuration().profile("default")
    controls = (as_logical_control("ring_finger"), as_logical_control("top_front"))
    profile = replace(
        profile,
        bindings=replace(
            profile.bindings, common=tuple(Binding(control, action) for control in controls)
        ),
    )
    dispatcher = ActionDispatcher(profile)
    sink = Sink()
    output = _output(kind, sink)
    for index, value in ((0, 1), (1, 1), (0, 0)):
        for intent in dispatcher.dispatch(controls[index], value).intents:
            if isinstance(output, keyboard.VirtualKeyboard):
                assert isinstance(intent, KeyOutputIntent)
                output.emit(intent)
            else:
                assert isinstance(intent, MouseButtonOutputIntent)
                output.emit(intent)
    code = 56 if kind == "keyboard" else 278
    assert sink.calls == [(1, code, 1), "syn"]
    final = dispatcher.dispatch(controls[1], 0).intents
    assert final == (
        (
            KeyOutputIntent("left_alt", 0)
            if kind == "keyboard"
            else MouseButtonOutputIntent("back", 0)
        ),
    )
    error = OSError("last owner release failed")
    sink.write_errors = [error]
    with pytest.raises(OSError) as caught:
        _emit(output, 0)
    assert caught.value is error
    assert sink.calls[-4:] == [(1, code, 0), (1, code, 0), "syn", "close"]


def test_combo_reaches_sink_in_modifier_then_key_and_reverse_release_order() -> None:
    profile = default_configuration().profile("default")
    control = as_logical_control("ring_finger")
    profile = replace(
        profile,
        bindings=replace(
            profile.bindings,
            common=(Binding(control, KeyComboAction(("left_alt", "left_ctrl"), "f")),),
        ),
    )
    dispatcher = ActionDispatcher(profile)
    sink = Sink()
    output = keyboard.VirtualKeyboard(
        sink, event_type=1, key_codes={"left_alt": 56, "left_ctrl": 29, "f": 33}
    )
    for value in (1, 0):
        for intent in dispatcher.dispatch(control, value).intents:
            assert isinstance(intent, KeyOutputIntent)
            output.emit(intent)
    ordered = ((56, 1), (29, 1), (33, 1), (33, 0), (29, 0), (56, 0))
    assert sink.calls == [event for code, value in ordered for event in ((1, code, value), "syn")]
    output.close()
    assert sink.calls[-1] == "close"
