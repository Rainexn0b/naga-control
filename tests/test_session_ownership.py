import asyncio
from collections.abc import AsyncIterator

import pytest
from test_first_slice_session import Actions, Output

from naga_control.adapters.evdev.discovery import EventNode, NagaConnection
from naga_control.application.remapping import (
    FirstSliceSession,
    PreparedSource,
    RunningSourceReader,
    create_source_reader,
)
from naga_control.domain.defaults import default_configuration
from naga_control.domain.profiles import Profile
from naga_control.ports.forwarding import (
    ForwardingProxyFactory,
    ForwardingProxySpec,
    ProxyReadinessWaiter,
)
from naga_control.ports.hardware import DeviceActionSubmitter
from naga_control.ports.output import KeyboardOutput, MouseOutput
from naga_control.service.source_forwarding import SourceActivationError


class TrackedOutput(Output):
    def __init__(self, events: list[str], name: str) -> None:
        super().__init__()
        self.events, self.name = events, name
        self.errors: dict[str, Exception] = {}

    def release_all(self) -> None:
        self.events.append(f"{self.name}.release")
        super().release_all()
        if error := self.errors.get("release"):
            raise error

    def close(self) -> None:
        self.events.append(f"{self.name}.close")
        super().close()
        if error := self.errors.get("close"):
            raise error


class TrackedActions(Actions):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events
        self.error: Exception | None = None
        self.stopping, self.release = asyncio.Event(), asyncio.Event()
        self.block = False

    async def start(self) -> None:
        self.events.append("actions.start")

    async def stop(self) -> None:
        self.events.append("actions.stop")
        self.stopping.set()
        if self.block:
            await self.release.wait()
        self.events.append("actions.stopped")
        if self.error is not None:
            raise self.error


class Source:
    def __init__(self, node: EventNode, events: list[str]) -> None:
        self.node, self.events = node, events
        self.forwarding_proxy_spec = ForwardingProxySpec("proxy", "phys", 3, 1, 2, 3, (), {})
        self.fault = ""
        self.error: BaseException | None = None
        self.grabbed = self.closed = False

    async def async_read_loop(self) -> AsyncIterator["InputEvent"]:
        await asyncio.Event().wait()
        yield InputEvent()

    def active_abs_values(self) -> dict[int, int]:
        return {}

    def active_keys(self) -> tuple[int, ...]:
        self.check("keys.after" if self.grabbed else "keys.before")
        return ()

    def check(self, phase: str) -> None:
        self.events.append(f"source.{phase}:{self.node.interface_number}")
        if self.fault == phase and self.error is not None:
            raise self.error

    def revalidate(self) -> None:
        self.check("revalidate")

    def drain_pending_frames(self) -> None:
        self.check("drain")

    def grab(self) -> None:
        self.check("grab")
        self.grabbed = True

    def ungrab(self) -> None:
        self.check("ungrab")
        self.grabbed = False

    def close(self) -> None:
        self.check("close")
        self.closed = True


class InputEvent:
    type = code = value = 0


class Proxy:
    def __init__(self, events: list[str]) -> None:
        self.events, self.closed = events, False

    def write(self, event_type: int, code: int, value: int) -> None:
        raise AssertionError("activation tests must not forward input")

    def flush(self) -> None:
        raise AssertionError("activation tests must not forward input")

    def close(self) -> None:
        self.events.append("proxy.close")
        self.closed = True


class ProxyFactory:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.proxies: list[Proxy] = []
        self.error: BaseException | None = None

    def create(self, spec: ForwardingProxySpec) -> Proxy:
        self.events.append("proxy.create")
        if self.error is not None:
            raise self.error
        proxy = Proxy(self.events)
        self.proxies.append(proxy)
        return proxy


class Waiter:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.error: BaseException | None = None

    def wait_ready(self, spec: ForwardingProxySpec) -> None:
        self.events.append("proxy.ready")
        if self.error is not None:
            raise self.error


class Reader:
    def __init__(self, source: PreparedSource, events: list[str]) -> None:
        self.source, self.events = source, events
        self.start_error: BaseException | None = None
        self.stop_error: Exception | None = None
        self.stopped = False

    def start(self) -> None:
        self.events.append(f"reader.start:{self.source.node.interface_number}")
        if self.start_error is not None:
            raise self.start_error

    async def run(self) -> object:
        await asyncio.Event().wait()

    def stop(self) -> None:
        if self.stopped:
            return
        self.stopped = True
        self.events.append(f"reader.stop:{self.source.node.interface_number}")
        self.source.close()  # stop owns cleanup even after failed activation.
        if self.stop_error is not None:
            raise self.stop_error


def connection() -> NagaConnection:
    nodes = tuple(
        EventNode(f"/dev/input/event{i}", "/sys/usb", i, "1532", "00e8") for i in ("00", "01", "02")
    )
    return NagaConnection("/sys/usb", "1532", "00e8", "hyperspeed", None, None, nodes)


@pytest.mark.parametrize("index", [0, 2], ids=["first", "later"])
@pytest.mark.parametrize("phase", ["factory", "start"])
@pytest.mark.parametrize("kind", [RuntimeError, asyncio.CancelledError, KeyboardInterrupt])
async def test_failed_reader_ownership_rolls_back_every_resource(
    index: int, phase: str, kind: type[BaseException]
) -> None:
    events: list[str] = []
    sources: list[Source] = []
    readers: list[Reader] = []
    keyboard, mouse = TrackedOutput(events, "keyboard"), TrackedOutput(events, "mouse")
    actions = TrackedActions(events)
    error = kind("activation interrupted")

    def open_source(node: EventNode) -> Source:
        source = Source(node, events)
        sources.append(source)
        return source

    def factory(
        source: PreparedSource,
        profile: Profile,
        keyboard: KeyboardOutput,
        mouse: MouseOutput,
        device_actions: DeviceActionSubmitter,
        proxy_factory: ForwardingProxyFactory,
        readiness_waiter: ProxyReadinessWaiter,
    ) -> RunningSourceReader:
        if len(sources) == index + 1 and phase == "factory":
            raise error
        reader = Reader(source, events)
        readers.append(reader)
        if len(sources) == index + 1:
            reader.start_error = error
        return reader

    session = FirstSliceSession(
        connection(),
        default_configuration().profile("default"),
        keyboard,
        mouse,
        actions,
        open_source,
        ProxyFactory(events),
        Waiter(events),
        factory,
    )
    baseline = asyncio.all_tasks()
    try:
        with pytest.raises(kind) as raised:
            async with asyncio.timeout(2):
                await session.start()
        assert raised.value is error
        assert all(source.closed for source in sources)
        assert all(reader.stopped for reader in readers)
        assert keyboard.released and mouse.released and keyboard.closed and mouse.closed
        assert events.count("actions.stopped") == 1
        assert not session.running
        assert not (asyncio.all_tasks() - baseline)
    finally:
        async with asyncio.timeout(2):
            await session.stop()


@pytest.mark.parametrize("phase", ["revalidate", "proxy", "ready", "drain", "keys.after"])
@pytest.mark.parametrize(
    "kind", [RuntimeError, KeyboardInterrupt, SystemExit, asyncio.CancelledError]
)
async def test_real_reader_interrupted_activation_fails_open(
    phase: str, kind: type[BaseException]
) -> None:
    events: list[str] = []
    source = Source(connection().nodes[0], events)
    source.fault, source.error = phase, kind("interrupted activation")
    factory, waiter = ProxyFactory(events), Waiter(events)
    if phase == "proxy":
        factory.error = source.error
    if phase == "ready":
        waiter.error = source.error
    keyboard, mouse = TrackedOutput(events, "keyboard"), TrackedOutput(events, "mouse")
    reader = create_source_reader(
        source,
        default_configuration().profile("default"),
        keyboard,
        mouse,
        TrackedActions(events),
        factory,
        waiter,
    )
    try:
        # Inject synchronously inside the awaited test, never in a child task.
        with pytest.raises(SourceActivationError if kind is RuntimeError else kind) as raised:
            reader.start()
        if kind is RuntimeError:
            assert raised.value.__cause__ is source.error
        else:
            assert raised.value is source.error
        assert source.closed and not source.grabbed
        assert all(proxy.closed for proxy in factory.proxies)
        assert keyboard.released and mouse.released
        if "source.grab:00" in events:
            assert events.index("proxy.ready") < events.index("source.grab:00")
            assert "source.ungrab:00" in events
    finally:
        reader.stop()
