"""Source cleanup attempts and pre-transfer rollback, using only fake descriptors."""

import asyncio
from collections.abc import Callable, Mapping, Sequence
from itertools import combinations
from typing import Literal, cast

import pytest
from test_evdev_source_adapter import FakeDevice, FakeInfo
from test_source_frame_consumer import Actions, Keyboard, Mouse, Proxy, Source

from naga_control.adapters.evdev.discovery import EventNode
from naga_control.adapters.evdev.frames import (
    EV_KEY,
    LogicalControlEvent,
    ParsedFrame,
    RawInputEvent,
)
from naga_control.adapters.evdev.source import open_evdev_source
from naga_control.domain.defaults import default_configuration
from naga_control.domain.intents import KeyOutputIntent
from naga_control.domain.profiles import as_logical_control
from naga_control.service.action_dispatcher import ActionDispatcher
from naga_control.service.frame_planner import FramePlanner
from naga_control.service.source_forwarding import SourceActivationError
from naga_control.service.source_frame_consumer import SourceFrameConsumer

RELEASES = ("planner-release", "keyboard-release", "mouse-release")
CLOSES = ("ungrab", "source-close", "proxy-close")
RELEASE_FAILURES = [subset for size in range(1, 4) for subset in combinations(RELEASES, size)]


class ConsumerRig:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, failures: tuple[str, ...]) -> None:
        self.calls: list[str] = []
        self.results: dict[str, object] = {}
        self.errors = {name: RuntimeError(f"private cleanup failure: {name}") for name in failures}
        self.source = Source()
        self.proxy = Proxy()
        self.keyboard = Keyboard()
        self.mouse = Mouse()
        self.planner = FramePlanner(ActionDispatcher(default_configuration().profile("default")))
        for owner, method, name in (
            (self.planner, "release_all", RELEASES[0]),
            (self.keyboard, "release_all", RELEASES[1]),
            (self.mouse, "release_all", RELEASES[2]),
            (self.source, "ungrab", CLOSES[0]),
            (self.source, "close", CLOSES[1]),
            (self.proxy, "close", CLOSES[2]),
        ):
            operation = cast(Callable[[], object], getattr(owner, method))
            monkeypatch.setattr(owner, method, self._attempt(name, operation))
        self.consumer = SourceFrameConsumer(
            self.planner, self.source, lambda: self.proxy, self.keyboard, self.mouse, Actions()
        )

    def _attempt(self, name: str, operation: Callable[[], object]) -> Callable[[], object]:
        def attempt() -> object:
            self.calls.append(name)
            if name in self.errors:
                raise self.errors[name]
            self.results[name] = operation()
            return self.results[name]

        return attempt


def _unsafe_frame() -> ParsedFrame:
    return ParsedFrame(
        (RawInputEvent(EV_KEY, 187, 0),),
        (LogicalControlEvent(as_logical_control("ring_finger"), 0, 4),),
    )


@pytest.mark.parametrize("failures", RELEASE_FAILURES)
def test_release_callback_attempts_every_port_and_raises_first_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failures: tuple[str, ...],
) -> None:
    rig = ConsumerRig(monkeypatch, failures)
    callback_name = "_release_outputs"
    release = cast(Callable[[], None], getattr(rig.consumer, callback_name))

    with pytest.raises(RuntimeError) as caught:
        release()

    assert caught.value is rig.errors[failures[0]]
    assert rig.calls == list(RELEASES)
    assert not rig.source.grabbed
    assert not rig.source.closed
    assert not rig.proxy.closed
    assert rig.proxy.events == []
    assert caplog.records == []


@pytest.mark.parametrize("failures", RELEASE_FAILURES)
@pytest.mark.parametrize("exit_path", ["stop", "unsafe"])
def test_release_failures_do_not_prevent_source_and_proxy_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failures: tuple[str, ...],
    exit_path: Literal["stop", "unsafe"],
) -> None:
    rig = ConsumerRig(monkeypatch, failures)
    rig.consumer.start()
    assert rig.source.grabbed

    if exit_path == "unsafe":
        with pytest.raises(SourceActivationError, match="unsafe frame"):
            rig.consumer.consume(_unsafe_frame())
    else:
        rig.consumer.stop()

    assert rig.calls == [*RELEASES, *CLOSES]
    assert not rig.source.grabbed
    assert rig.source.closed
    assert rig.proxy.closed
    assert rig.proxy.events == []
    assert caplog.records == []
    rig.consumer.stop()
    rig.consumer.consume(ParsedFrame((RawInputEvent(EV_KEY, 30, 1),), ()))
    assert rig.calls == [*RELEASES, *CLOSES]
    assert rig.proxy.events == []


@pytest.mark.parametrize("failures", [(name,) for name in CLOSES] + [CLOSES])
@pytest.mark.parametrize("release_fails", [False, True])
@pytest.mark.parametrize("exit_path", ["stop", "unsafe"])
def test_ordinary_descriptor_cleanup_errors_do_not_skip_later_attempts(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failures: tuple[str, ...],
    release_fails: bool,
    exit_path: Literal["stop", "unsafe"],
) -> None:
    rig = ConsumerRig(monkeypatch, failures + (RELEASES if release_fails else ()))
    rig.consumer.start()

    if exit_path == "unsafe":
        with pytest.raises(SourceActivationError, match="unsafe frame"):
            rig.consumer.consume(_unsafe_frame())
    else:
        rig.consumer.stop()

    # A failed attempt is not evidence that the underlying resource was released.
    assert rig.calls == [*RELEASES, *CLOSES]
    assert rig.source.closed == ("source-close" not in failures)
    assert rig.proxy.closed == ("proxy-close" not in failures)
    assert rig.source.grabbed == ("ungrab" in failures)
    assert caplog.records == []
    rig.consumer.stop()
    assert rig.calls == [*RELEASES, *CLOSES]


def test_held_planner_release_intents_are_cleared_and_ports_release_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = ConsumerRig(monkeypatch, ())
    rig.consumer.start()
    rig.consumer.consume(
        ParsedFrame(
            (RawInputEvent(EV_KEY, 187, 1),),
            (LogicalControlEvent(as_logical_control("ring_finger"), 1, 0),),
        )
    )
    assert rig.keyboard.intents == [KeyOutputIntent("left_alt", 1)]

    rig.consumer.stop()

    assert rig.results["planner-release"] == (KeyOutputIntent("left_alt", 0),)
    assert rig.planner.release_all() == ()
    assert rig.results["planner-release"] == ()
    assert rig.keyboard.intents == [KeyOutputIntent("left_alt", 1)]
    assert rig.keyboard.released
    assert rig.mouse.released
    assert rig.source.closed and rig.proxy.closed


class InterruptedDevice(FakeDevice):
    def __init__(self, phase: str, error: BaseException, close_error: Exception | None) -> None:
        super().__init__({EV_KEY: (30,)})
        self.phase = phase
        self.error = error
        self.close_error = close_error
        self.calls: list[str] = []

    def checkpoint(self, phase: str) -> None:
        self.calls.append(phase)
        if self.phase == phase:
            raise self.error

    @property
    def fd(self) -> int:
        self.checkpoint("fd")
        return 42

    @property
    def info(self) -> FakeInfo:
        self.checkpoint("info")
        return FakeInfo()

    def capabilities(
        self, verbose: bool = False, absinfo: bool = True
    ) -> Mapping[int, Sequence[object]]:
        self.checkpoint("capabilities")
        return super().capabilities(verbose, absinfo)

    def input_props(self, verbose: bool = False) -> Sequence[int]:
        self.checkpoint("input_props")
        return super().input_props(verbose)

    def close(self) -> None:
        self.calls.append("close")
        if self.close_error is not None:
            raise self.close_error
        super().close()

    def grab(self) -> None:
        pytest.fail("opening a source must not grab it")


@pytest.mark.parametrize(
    "phase", ["fd", "device_number", "identity", "capabilities", "info", "input_props"]
)
@pytest.mark.parametrize(
    "error_type", [OSError, RuntimeError, asyncio.CancelledError, KeyboardInterrupt]
)
@pytest.mark.parametrize("close_fails", [False, True])
def test_open_source_rolls_back_before_transfer_and_preserves_primary_failure(
    phase: str,
    error_type: type[BaseException],
    close_fails: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    node = EventNode(
        event_path="/dev/input/fake-source",
        usb_path="/sys/devices/fake-physical-usb",
        interface_number="01",
        vendor_id="1532",
        product_id="00e8",
        serial=None,
        physical_path=None,
    )
    error = error_type("private primary failure")
    device = InterruptedDevice(
        phase, error, OSError("private close failure") if close_fails else None
    )

    def factory(path: str) -> InterruptedDevice:
        assert path == node.event_path
        device.calls.append("factory")
        return device

    def device_number(fd: int) -> int:
        assert fd == 42
        device.checkpoint("device_number")
        return 123

    def identity(number: int) -> EventNode:
        assert number == 123
        device.checkpoint("identity")
        return node

    # Catch secondary close failures too, so failed identity assertions expose masking.
    with pytest.raises(BaseException) as caught:
        open_evdev_source(
            node,
            device_factory=factory,
            device_number_resolver=device_number,
            identity_resolver=identity,
        )

    assert caught.value is error
    checkpoints = [
        "factory",
        "fd",
        "device_number",
        "identity",
        "capabilities",
        "info",
        "input_props",
    ]
    assert device.calls == [*checkpoints[: checkpoints.index(phase) + 1], "close"]
    assert device.closed == (not close_fails)
    assert caplog.records == []
