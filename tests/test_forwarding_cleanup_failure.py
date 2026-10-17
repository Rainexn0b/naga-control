"""Strict forwarding cleanup barrier: first error wins, all resources attempted."""

import pytest
from reader_failure_fakes import FakeManagedSource, FakeProxy

from naga_control.adapters.evdev.discovery import EventNode
from naga_control.adapters.evdev.frames import (
    EV_KEY,
    FrameParser,
    LogicalControlEvent,
    ParsedFrame,
    RawControlSignature,
    RawInputEvent,
)
from naga_control.domain.defaults import default_configuration
from naga_control.domain.profiles import as_logical_control
from naga_control.service.action_dispatcher import ActionDispatcher
from naga_control.service.frame_planner import ForwardingPlan
from naga_control.service.session_lifecycle import SessionLifecycle
from naga_control.service.source_forwarding import SourceActivationError, SourceForwarder
from naga_control.service.source_frame_consumer import SourceFrameConsumer
from naga_control.service.source_reader import SourceReader


class Rig:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.source = FakeManagedSource(self.calls)
        self.proxy = FakeProxy(self.calls)
        self.forwarder = SourceForwarder(
            self.source,
            lambda: self._prepare(),
            self.source.release_generated_outputs,
        )

    def _prepare(self) -> FakeProxy:
        self.calls.append("prepare")
        return self.proxy


def _started_rig() -> Rig:
    rig = Rig()
    rig.forwarder.start()
    rig.calls.clear()
    return rig


def test_cleanup_attempts_every_resource_and_caches_first_error() -> None:
    rig = _started_rig()
    release = RuntimeError("release failed")
    ungrab = OSError("ungrab failed")
    rig.source.release_error = release
    rig.source.ungrab_error = ungrab
    rig.source.close_error = OSError("close failed")
    rig.proxy.close_error = OSError("proxy failed")
    with pytest.raises(RuntimeError) as caught:
        rig.forwarder.stop()
    assert caught.value is release
    assert rig.calls == ["release", "ungrab", "source-close", "proxy-close"]
    before = list(rig.calls)
    with pytest.raises(RuntimeError) as cached:
        rig.forwarder.stop()
    assert cached.value is release
    assert rig.calls == before
    with pytest.raises(RuntimeError) as blocked:
        rig.forwarder.start()
    assert blocked.value is release
    with pytest.raises(RuntimeError) as blocked_forward:
        rig.forwarder.forward(ForwardingPlan(()))
    assert blocked_forward.value is release


@pytest.mark.parametrize("failing", ["release", "ungrab", "source-close", "proxy-close"])
def test_each_single_cleanup_fault_is_a_barrier(failing: str) -> None:
    rig = _started_rig()
    errors = {
        "release": RuntimeError("release"),
        "ungrab": OSError("ungrab"),
        "source-close": OSError("close"),
        "proxy-close": OSError("proxy"),
    }
    if failing == "release":
        rig.source.release_error = errors[failing]
    elif failing == "ungrab":
        rig.source.ungrab_error = errors[failing]
    elif failing == "source-close":
        rig.source.close_error = errors[failing]
    else:
        rig.proxy.close_error = errors[failing]
    with pytest.raises(Exception) as caught:
        rig.forwarder.stop()
    assert caught.value is errors[failing]
    assert rig.calls == ["release", "ungrab", "source-close", "proxy-close"]
    with pytest.raises(Exception) as cached:
        rig.forwarder.stop()
    assert cached.value is errors[failing]


def test_start_preserves_primary_and_caches_cleanup_for_later_stop() -> None:
    calls: list[str] = []
    source = FakeManagedSource(calls)
    cleanup = OSError("cleanup close failed")
    source.close_error = cleanup
    primary = RuntimeError("primary prepare failed")

    def prepare() -> FakeProxy:
        calls.append("prepare")
        raise primary

    forwarder = SourceForwarder(source, prepare, source.release_generated_outputs)
    with pytest.raises(SourceActivationError) as raised:
        forwarder.start()
    assert isinstance(raised.value, SourceActivationError)
    assert raised.value.__cause__ is primary
    with pytest.raises(OSError) as cached:
        forwarder.stop()
    assert cached.value is cleanup
    assert calls.count("source-close") == 1
    with pytest.raises(OSError) as again:
        forwarder.stop()
    assert again.value is cleanup
    assert calls.count("source-close") == 1


def test_forward_preserves_primary_write_error() -> None:
    rig = _started_rig()
    cleanup = OSError("cleanup ungrab failed")
    rig.source.ungrab_error = cleanup
    primary = OSError("forward write failed")

    class FailingProxy(FakeProxy):
        def write(self, event_type: int, code: int, value: int) -> None:
            raise primary

    rig.forwarder._proxy = FailingProxy(rig.calls)  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(OSError) as raised:
        rig.forwarder.forward(ForwardingPlan((RawInputEvent(1, 30, 1),)))
    assert raised.value is primary
    before = list(rig.calls)
    with pytest.raises(OSError) as cached:
        rig.forwarder.stop()
    assert cached.value is cleanup
    assert rig.calls == before
    with pytest.raises(OSError) as again:
        rig.forwarder.stop()
    assert again.value is cleanup
    assert rig.calls == before


def test_consumer_preserves_emit_primary_and_surfaces_cleanup_on_stop() -> None:
    from test_source_frame_consumer import Actions, Keyboard, Mouse, Proxy, Source

    from naga_control.service.frame_planner import FramePlanner as Planner

    source, proxy = Source(), Proxy()
    keyboard, mouse = Keyboard(), Mouse()
    planner = Planner(ActionDispatcher(default_configuration().profile("default")))
    consumer = SourceFrameConsumer(planner, source, lambda: proxy, keyboard, mouse, Actions())
    consumer.start()
    primary = RuntimeError("private emit failure")
    keyboard_emit = keyboard.emit

    def emit(intent: object) -> None:
        raise primary

    keyboard.emit = emit  # type: ignore[method-assign]
    proxy.close = lambda: (_ for _ in ()).throw(OSError("cleanup proxy failed"))  # type: ignore[method-assign]
    with pytest.raises(RuntimeError) as raised:
        consumer.consume(
            ParsedFrame(
                (RawInputEvent(EV_KEY, 187, 1),),
                (LogicalControlEvent(as_logical_control("ring_finger"), 1, 0),),
            )
        )
    assert raised.value is primary
    with pytest.raises(OSError, match="cleanup proxy failed"):
        consumer.stop()
    keyboard.emit = keyboard_emit


def _test_parser() -> FrameParser:
    node = EventNode(
        event_path="/dev/input/event5",
        usb_path="/sys/devices/usb-receiver",
        interface_number="01",
        vendor_id="1532",
        product_id="00e8",
    )
    signature = RawControlSignature("00e8", "01", EV_KEY, 187, 458860)
    return FrameParser(node, {signature: "ring_finger"})


def test_reader_caches_first_stop_failure_and_blocks_restart() -> None:
    from test_source_reader import Sink, Source

    sink = Sink()
    reader = SourceReader(Source(), _test_parser(), sink)
    first = OSError("first stop failure")

    def failing_stop() -> None:
        sink.events.append("stop")
        raise first

    sink.stop = failing_stop  # type: ignore[method-assign]
    reader.start()
    with pytest.raises(OSError) as raised:
        reader.stop()
    assert raised.value is first
    with pytest.raises(OSError) as cached:
        reader.stop()
    assert cached.value is first
    with pytest.raises(OSError) as blocked:
        reader.start()
    assert blocked.value is first


def test_reader_owns_stop_when_sink_start_raises() -> None:
    from test_source_reader import Source

    primary = RuntimeError("sink start failed")

    class FailingSink:
        def __init__(self) -> None:
            self.stops = 0

        def start(self) -> None:
            raise primary

        def consume(self, frame: ParsedFrame) -> None:
            raise AssertionError("must not consume")

        def stop(self) -> None:
            self.stops += 1

    sink = FailingSink()
    reader = SourceReader(Source(), _test_parser(), sink)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError) as raised:
        reader.start()
    assert raised.value is primary
    reader.stop()
    assert sink.stops == 1


async def test_failed_lifecycle_stop_stays_unsafe() -> None:
    events: list[str] = []
    error = OSError("genuine cleanup failure")

    class FailingSession:
        async def start(self) -> None:
            events.append("start")

        async def stop(self) -> None:
            events.append("stop")
            raise error

        def release_all(self) -> None:
            events.append("release")

    lifecycle = SessionLifecycle(lambda: events.append("fence"))
    await lifecycle.start(FailingSession())  # type: ignore[arg-type]
    with pytest.raises(OSError) as raised:
        await lifecycle.stop()
    assert raised.value is error
    assert lifecycle.unsafe
    assert lifecycle.current is None


async def test_real_stack_double_fault_blocks_replacement_with_first_error() -> None:
    import asyncio as _asyncio

    from reader_failure_fakes import make_connection

    from naga_control.application.remapping import FirstSliceSession, create_source_reader
    from naga_control.domain.defaults import default_configuration
    from naga_control.ports.forwarding import ForwardingProxySpec

    events: list[str] = []
    first = OSError(5, "genuine source close failed")
    second = OSError(5, "later proxy close failed")

    class StackSource:
        def __init__(self, node: object) -> None:
            self.node = node
            self.forwarding_proxy_spec = ForwardingProxySpec(
                "proxy-01", "phys-01", 3, 1, 2, 3, (), {}
            )

        async def async_read_loop(self):  # type: ignore[no-untyped-def]
            await _asyncio.Event().wait()
            yield object()

        def active_keys(self) -> tuple[int, ...]:
            return ()

        def active_abs_values(self) -> dict[int, int]:
            return {}

        def revalidate(self) -> None:
            events.append("revalidate")

        def drain_pending_frames(self) -> None:
            events.append("drain")

        def grab(self) -> None:
            events.append("grab")

        def ungrab(self) -> None:
            events.append("ungrab")

        def close(self) -> None:
            events.append("source-close")
            raise first

    class StackProxy:
        def write(self, event_type: int, code: int, value: int) -> None:
            return None

        def flush(self) -> None:
            return None

        def close(self) -> None:
            events.append("proxy-close")
            raise second

    class StackKeyboard:
        def release_all(self) -> None:
            events.append("keyboard.release")

        def close(self) -> None:
            events.append("keyboard.close")

        def emit(self, intent: object) -> None:
            return None

    class StackMouse(StackKeyboard):
        pass

    class StackActions:
        async def start(self) -> None:
            events.append("actions.start")

        async def stop(self) -> None:
            events.append("actions.stop")

        def submit(self, intent: object) -> bool:
            return True

    class StackFactory:
        def create(self, spec: ForwardingProxySpec) -> StackProxy:
            events.append("proxy.create")
            return StackProxy()

    class StackWaiter:
        def wait_ready(self, spec: ForwardingProxySpec) -> None:
            events.append("proxy.ready")

    connection = make_connection(("01",))
    profile = default_configuration().profile("default")
    session = FirstSliceSession(
        connection,
        profile,
        StackKeyboard(),  # type: ignore[arg-type]
        StackMouse(),  # type: ignore[arg-type]
        StackActions(),  # type: ignore[arg-type]
        lambda node: StackSource(node),  # type: ignore[return-value]
        StackFactory(),  # type: ignore[arg-type]
        StackWaiter(),  # type: ignore[arg-type]
        lambda source, p, k, m, d, f, w: create_source_reader(
            source,
            p,
            k,
            m,
            d,
            f,
            w,  # type: ignore[arg-type]
        ),
    )
    lifecycle = SessionLifecycle(lambda: events.append("fence"))
    try:
        await lifecycle.start(session)  # type: ignore[arg-type]
        with pytest.raises(OSError) as raised:
            await _asyncio.wait_for(lifecycle.stop(), 2)
        assert raised.value is first
        assert lifecycle.unsafe
        assert lifecycle.current is None
        assert events.count("source-close") == 1
        assert events.count("proxy-close") == 1
        before = list(events)
        with pytest.raises(OSError) as cached:
            await _asyncio.wait_for(session.stop(), 2)
        assert cached.value is first
        assert events == before
    finally:
        await _asyncio.gather(session.stop(), return_exceptions=True)
