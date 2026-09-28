import pytest

from naga_control.adapters.evdev.frames import EV_SYN, SYN_REPORT, RawInputEvent
from naga_control.service.frame_planner import ForwardingPlan
from naga_control.service.source_forwarding import SourceActivationError, SourceForwarder


class FakeSource:
    def __init__(
        self, calls: list[str], *, held_before: bool = False, held_after: bool = False
    ) -> None:
        self.calls = calls
        self.held_before = held_before
        self.held_after = held_after
        self.grabbed = False

    def revalidate(self) -> None:
        self.calls.append("revalidate")

    def drain_pending_frames(self) -> None:
        self.calls.append("drain")

    def active_keys(self) -> tuple[int, ...]:
        self.calls.append("keys")
        return (1,) if (self.held_after if self.grabbed else self.held_before) else ()

    def grab(self) -> None:
        self.calls.append("grab")
        self.grabbed = True

    def ungrab(self) -> None:
        self.calls.append("ungrab")
        self.grabbed = False

    def close(self) -> None:
        self.calls.append("close-source")


class FakeProxy:
    def __init__(self, calls: list[str], *, fail_write: bool = False) -> None:
        self.calls = calls
        self.fail_write = fail_write

    def write(self, event_type: int, code: int, value: int) -> None:
        self.calls.append(f"write:{event_type}:{code}:{value}")
        if self.fail_write:
            raise OSError("proxy write failed")

    def flush(self) -> None:
        self.calls.append("flush")

    def close(self) -> None:
        self.calls.append("close-proxy")


def test_start_prepares_proxy_before_grabbing() -> None:
    calls: list[str] = []
    source = FakeSource(calls)
    forwarder = SourceForwarder(
        source,
        lambda: _prepare(calls),
        lambda: calls.append("release-output"),
    )

    forwarder.start()

    assert calls == ["revalidate", "prepare", "drain", "keys", "grab", "keys"]


def test_held_key_before_grab_fails_open_without_grabbing() -> None:
    calls: list[str] = []
    source = FakeSource(calls, held_before=True)

    with pytest.raises(SourceActivationError, match="held"):
        SourceForwarder(
            source, lambda: _prepare(calls), lambda: calls.append("release-output")
        ).start()

    assert "grab" not in calls
    assert calls[-3:] == ["release-output", "close-source", "close-proxy"]


def test_held_key_after_grab_releases_the_grab_and_closes_both_sides() -> None:
    calls: list[str] = []
    source = FakeSource(calls, held_after=True)

    with pytest.raises(SourceActivationError, match="held"):
        SourceForwarder(
            source, lambda: _prepare(calls), lambda: calls.append("release-output")
        ).start()

    assert calls[-4:] == ["release-output", "ungrab", "close-source", "close-proxy"]


def test_forwarding_preserves_order_and_converts_only_syn_report_to_flush() -> None:
    calls: list[str] = []
    forwarder = SourceForwarder(
        FakeSource(calls),
        lambda: _prepare(calls),
        lambda: calls.append("release-output"),
    )
    forwarder.start()

    forwarder.forward(
        ForwardingPlan(
            (
                RawInputEvent(4, 4, 123),
                RawInputEvent(1, 30, 1),
                RawInputEvent(EV_SYN, SYN_REPORT, 0),
            )
        )
    )

    assert calls[-3:] == ["write:4:4:123", "write:1:30:1", "flush"]


def test_proxy_write_failure_releases_outputs_and_fails_open() -> None:
    calls: list[str] = []
    forwarder = SourceForwarder(
        FakeSource(calls),
        lambda: FakeProxy(calls, fail_write=True),
        lambda: calls.append("release-output"),
    )
    forwarder.start()

    with pytest.raises(OSError, match="proxy write failed"):
        forwarder.forward(ForwardingPlan((RawInputEvent(1, 30, 1),)))

    assert calls[-4:] == ["release-output", "ungrab", "close-source", "close-proxy"]


def _prepare(calls: list[str]) -> FakeProxy:
    calls.append("prepare")
    return FakeProxy(calls)
