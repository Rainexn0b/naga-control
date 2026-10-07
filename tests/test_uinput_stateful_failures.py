"""Explicit conventional simulation, not evidence of Linux kernel release semantics."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import pytest

from naga_control.adapters.uinput.keyboard import VirtualKeyboard
from naga_control.adapters.uinput.mouse import VirtualMouse
from naga_control.domain.intents import KeyOutputIntent, MouseButtonOutputIntent

type Timing = Literal["before", "after"]
type Kind = Literal["keyboard", "mouse"]
type Call = tuple[int, int, int] | str


@dataclass(frozen=True)
class Fault:
    error: Exception
    timing: Timing


class StatefulSink:
    """Writes update accepted holds; syn publishes them; destruction clears both."""

    def __init__(self) -> None:
        self.calls: list[Call] = []
        self.accepted: list[tuple[int, int]] = []
        self.held: set[int] = set()
        self.published: frozenset[int] = frozenset()
        self.frames: list[frozenset[int]] = []
        self.destroyed = False
        self.held_at_close: frozenset[int] | None = None
        self.faults: dict[str, list[Fault | None]] = {"write": [], "syn": [], "close": []}

    def _perform(self, operation: str, effect: Callable[[], None]) -> None:
        pending = self.faults[operation]
        fault = pending.pop(0) if pending else None
        if fault is not None and fault.timing == "before":
            raise fault.error
        effect()
        if fault is not None:
            raise fault.error

    def write(self, event_type: int, code: int, value: int) -> None:
        assert not self.destroyed
        assert event_type == 1 and value in {0, 1}
        self.calls.append((event_type, code, value))

        def accept() -> None:
            self.accepted.append((code, value))
            if value == 1:
                self.held.add(code)
            else:
                self.held.discard(code)

        self._perform("write", accept)

    def syn(self) -> None:
        assert not self.destroyed
        self.calls.append("syn")

        def publish() -> None:
            self.published = frozenset(self.held)
            self.frames.append(self.published)

        self._perform("syn", publish)

    def close(self) -> None:
        assert not self.destroyed
        self.calls.append("close")
        self.held_at_close = frozenset(self.held)

        def destroy() -> None:
            self.destroyed = True
            self.held.clear()
            self.published = frozenset()

        self._perform("close", destroy)


def _output(kind: Kind, sink: StatefulSink) -> VirtualKeyboard | VirtualMouse:
    # Codes are placeholders, not a physical input identity or Linux capability test.
    if kind == "keyboard":
        return VirtualKeyboard(sink, event_type=1, key_codes={"left_alt": 101, "left_ctrl": 102})
    return VirtualMouse(sink, event_type=1, button_codes={"back": 101, "forward": 102})


def _emit(
    output: VirtualKeyboard | VirtualMouse, index: Literal[0, 1], value: Literal[0, 1]
) -> None:
    if isinstance(output, VirtualKeyboard):
        output.emit(KeyOutputIntent(("left_alt", "left_ctrl")[index], value))
    else:
        output.emit(MouseButtonOutputIntent(("back", "forward")[index], value))


def _assert_logically_closed(output: VirtualKeyboard | VirtualMouse, sink: StatefulSink) -> None:
    before = sink.calls.copy()
    state = (sink.held.copy(), sink.published, sink.destroyed)
    with pytest.raises(OSError, match="closed"):
        _emit(output, 0, 1)
    output.release_all()
    output.close()
    assert sink.calls == before
    assert (sink.held, sink.published, sink.destroyed) == state


@pytest.mark.parametrize("kind", ["keyboard", "mouse"])
@pytest.mark.parametrize("phase", ["write", "syn"])
@pytest.mark.parametrize("timing", ["before", "after"])
@pytest.mark.parametrize("error_type", [OSError, RuntimeError])
def test_failed_press_successful_destruction_clears_even_unreleased_simulated_holds(
    kind: Kind, phase: str, timing: Timing, error_type: type[Exception]
) -> None:
    sink = StatefulSink()
    output = _output(kind, sink)
    error = error_type("press failed")
    release_fault = Fault(RuntimeError("release rejected"), "before")
    sync_fault = Fault(RuntimeError("cleanup sync failed"), timing)
    sink.faults["write"] = [Fault(error, timing) if phase == "write" else None, release_fault]
    sink.faults["syn"] = [sync_fault]
    if phase == "syn":
        sink.faults["syn"].insert(0, Fault(error, timing))

    with pytest.raises(error_type) as caught:
        _emit(output, 0, 1)

    assert caught.value is error
    accepted_down = phase == "syn" or timing == "after"
    assert sink.accepted == ([(101, 1)] if accepted_down else [])
    assert sink.held_at_close == (frozenset({101}) if accepted_down else frozenset())
    attempted: list[Call] = [(1, 101, 1)]
    if phase == "syn":
        attempted.append("syn")
    assert sink.calls == [*attempted, (1, 101, 0), "syn", "close"]
    assert len(sink.frames) == ((2 if phase == "syn" else 1) if timing == "after" else 0)
    assert sink.destroyed
    assert sink.held == set() and sink.published == frozenset()
    assert all(not faults for faults in sink.faults.values())
    _assert_logically_closed(output, sink)


@pytest.mark.parametrize("kind", ["keyboard", "mouse"])
@pytest.mark.parametrize("operation", ["release_all", "close"])
@pytest.mark.parametrize("write_timing", ["before", "after"])
@pytest.mark.parametrize("syn_timing", ["before", "after"])
@pytest.mark.parametrize("close_timing", ["before", "after"])
def test_cleanup_error_keeps_first_failure_without_promising_resource_release(
    kind: Kind, operation: str, write_timing: Timing, syn_timing: Timing, close_timing: Timing
) -> None:
    sink = StatefulSink()
    output = _output(kind, sink)
    _emit(output, 0, 1)
    _emit(output, 1, 1)
    assert sink.held == {101, 102} and sink.published == frozenset({101, 102})
    sink.calls.clear()
    error = OSError("first release failed")
    # Both release_all's initial pass and fail-closed fallback fault on every release.
    sink.faults["write"] = [Fault(error, write_timing)]
    sink.faults["write"].extend(
        Fault(RuntimeError("secondary release failed"), write_timing) for _ in range(3)
    )
    sink.faults["syn"] = [Fault(RuntimeError("sync failed"), syn_timing) for _ in range(2)]
    sink.faults["close"] = [Fault(RuntimeError("close failed"), close_timing)]

    with pytest.raises(OSError) as caught:
        getattr(output, operation)()

    assert caught.value is error
    releases = [call for call in sink.calls if isinstance(call, tuple)]
    assert releases[:2] == releases[2:]  # Both owned codes attempted in each pass.
    assert set(releases) == {(1, 101, 0), (1, 102, 0)}
    accepted_ups = [(code, value) for _, code, value in releases] if write_timing == "after" else []
    assert sink.accepted[2:] == accepted_ups
    assert sink.held_at_close == (
        frozenset({101, 102}) if write_timing == "before" else frozenset()
    )
    assert sink.calls[2] == "syn" and sink.calls[-2:] == ["syn", "close"]
    assert sink.calls.count("close") == 1
    assert all(not faults for faults in sink.faults.values())
    if close_timing == "before":
        assert not sink.destroyed
        if write_timing == "before":
            assert sink.held == {101, 102}  # Logical closure does not establish destruction.
    # A close exception never requires an empty simulated held set or released resource.
    _assert_logically_closed(output, sink)


@pytest.mark.parametrize("kind", ["keyboard", "mouse"])
def test_successful_release_all_clears_simulated_holds_before_later_destruction(kind: Kind) -> None:
    sink = StatefulSink()
    output = _output(kind, sink)
    _emit(output, 0, 1)
    _emit(output, 1, 1)
    assert sink.held == {101, 102}

    output.release_all()

    assert sink.held == set() and sink.published == frozenset()
    assert not sink.destroyed and "close" not in sink.calls
    output.close()
    assert sink.held_at_close == frozenset()
    assert sink.destroyed and sink.calls.count("close") == 1
    _assert_logically_closed(output, sink)
