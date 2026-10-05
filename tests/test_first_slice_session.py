import asyncio
from collections.abc import AsyncIterator

from naga_control.adapters.evdev.discovery import EventNode, NagaConnection
from naga_control.application.remapping import FirstSliceSession, PreparedSource
from naga_control.domain.defaults import default_configuration
from naga_control.domain.intents import DeviceActionIntent, KeyOutputIntent, MouseButtonOutputIntent
from naga_control.ports.forwarding import (
    ForwardingProxy,
    ForwardingProxySpec,
)


class Output:
    def __init__(self) -> None:
        self.released = False
        self.closed = False

    def emit(self, intent: KeyOutputIntent | MouseButtonOutputIntent) -> None:
        return None

    def release_all(self) -> None:
        self.released = True

    def close(self) -> None:
        self.closed = True


class Actions:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def start(self) -> None:
        self.events.append("start")

    async def stop(self) -> None:
        self.events.append("stop")

    def submit(self, intent: DeviceActionIntent) -> bool:
        return True


class Reader:
    def __init__(self, node: EventNode, events: list[str]) -> None:
        self._node = node
        self._events = events
        self._started = False

    def start(self) -> None:
        self._started = True

    async def run(self) -> object:
        self._events.append(f"run:{self._node.interface_number}")
        try:
            await asyncio.Event().wait()
        finally:
            self.stop()

    def stop(self) -> None:
        if self._started:
            self._started = False
            self._events.append(f"stop:{self._node.interface_number}")


def test_session_opens_only_fixture_backed_interfaces_and_releases_on_stop() -> None:
    asyncio.run(_exercise_session())


async def test_session_stop_closes_readers_cancelled_before_first_run() -> None:
    events: list[str] = []
    session = FirstSliceSession(
        _connection(),
        default_configuration().profile("default"),
        Output(),
        Output(),
        Actions(),
        _source,
        _ProxyFactory(),
        _Waiter(),
        reader_factory=lambda source, profile, keyboard, mouse, device_actions, proxy_factory, readiness_waiter: (
            Reader(source.node, events)
        ),
    )
    await session.start()
    await session.stop()
    assert events == ["stop:00", "stop:01", "stop:02"]


async def _exercise_session() -> None:
    events: list[str] = []
    opened: list[str] = []
    keyboard = Output()
    mouse = Output()
    actions = Actions()
    connection = _connection()

    session = FirstSliceSession(
        connection,
        default_configuration().profile("default"),
        keyboard,
        mouse,
        actions,
        lambda node: _source(node),
        _ProxyFactory(),
        _Waiter(),
        reader_factory=lambda source, profile, keyboard, mouse, device_actions, proxy_factory, readiness_waiter: (
            _reader(source, opened, events)
        ),
    )
    await session.start()
    await asyncio.sleep(0)
    await session.stop()

    assert opened == ["00", "01", "02"]
    assert events == ["run:00", "run:01", "run:02", "stop:00", "stop:01", "stop:02"]
    assert actions.events == ["start", "stop"]
    assert keyboard.released and keyboard.closed
    assert mouse.released and mouse.closed


async def test_session_start_failure_closes_shared_outputs() -> None:
    keyboard = Output()
    mouse = Output()
    actions = Actions()
    session = FirstSliceSession(
        _connection(),
        default_configuration().profile("default"),
        keyboard,
        mouse,
        actions,
        lambda node: _source(node),
        _ProxyFactory(),
        _Waiter(),
        reader_factory=lambda source, profile, keyboard, mouse, device_actions, proxy_factory, readiness_waiter: (
            _FailingReader()
        ),
    )

    try:
        await session.start()
    except RuntimeError as error:
        assert str(error) == "physical source is already grabbed"
    else:
        raise AssertionError("session startup should fail")

    assert actions.events == ["start", "stop"]
    assert keyboard.released and keyboard.closed
    assert mouse.released and mouse.closed


class _FailingReader:
    def start(self) -> None:
        raise RuntimeError("physical source is already grabbed")

    async def run(self) -> object:
        raise AssertionError("failed readers must not run")

    def stop(self) -> None:
        return None


def _connection() -> NagaConnection:
    nodes = tuple(_node(interface) for interface in ("00", "01", "02"))
    return NagaConnection("/sys/usb", "1532", "00e8", "hyperspeed", None, None, nodes)


def _node(interface: str) -> EventNode:
    return EventNode(f"/dev/input/event{interface}", "/sys/usb", interface, "1532", "00e8")


def _source(node: EventNode) -> PreparedSource:
    return _Source(node)


class _Source:
    def __init__(self, node: EventNode) -> None:
        self.node = node
        self.forwarding_proxy_spec = ForwardingProxySpec("proxy", "phys", 3, 1, 2, 3, (), {})

    async def async_read_loop(self) -> AsyncIterator["_Event"]:
        if False:
            yield _Event()

    def active_keys(self) -> tuple[int, ...]:
        return ()

    def active_abs_values(self) -> dict[int, int]:
        return {}

    def revalidate(self) -> None:
        return None

    def drain_pending_frames(self) -> None:
        return None

    def grab(self) -> None:
        return None

    def ungrab(self) -> None:
        return None

    def close(self) -> None:
        return None


class _Event:
    type = 0
    code = 0
    value = 0


def _reader(source: PreparedSource, opened: list[str], events: list[str]) -> Reader:
    opened.append(source.node.interface_number)
    return Reader(source.node, events)


class _ProxyFactory:
    def create(self, spec: ForwardingProxySpec) -> ForwardingProxy:
        raise AssertionError("fake readers do not create proxies")


class _Waiter:
    def wait_ready(self, spec: ForwardingProxySpec) -> None:
        raise AssertionError("fake readers do not wait")
