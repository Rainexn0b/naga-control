"""DEBT-15 OpenRazer pre-transfer raw connection rollback using only fakes."""

import asyncio
from types import ModuleType

import pytest

from naga_control.adapters.openrazer import lifecycle_monitor


class _Connected:
    def __init__(self) -> None:
        self.calls: list[object] = []
        self.handlers: list[object] = []
        self.disconnects = 0

    async def call(self, message: object) -> object:
        self.calls.append(message)
        return object()

    def add_message_handler(self, handler: object) -> None:
        self.handlers.append(handler)

    def remove_message_handler(self, handler: object) -> None:
        if handler in self.handlers:
            self.handlers.remove(handler)

    def disconnect(self) -> None:
        self.disconnects += 1


class _Raw:
    def __init__(
        self,
        events: list[str],
        connected: _Connected,
        error: BaseException | None = None,
        disconnect_error: Exception | None = None,
    ) -> None:
        self._events = events
        self._connected = connected
        self._error = error
        self._disconnect_error = disconnect_error
        self.disconnects = 0

    async def connect(self) -> _Connected:
        self._events.append("connect")
        if self._error is not None:
            raise self._error
        return self._connected

    def disconnect(self) -> None:
        self._events.append("disconnect")
        self.disconnects += 1
        if self._disconnect_error is not None:
            raise self._disconnect_error


def _install(
    monkeypatch: pytest.MonkeyPatch,
    session: object,
    raw: _Raw,
    events: list[str],
    constructor_error: BaseException | None = None,
    message_factory: object | None = None,
) -> None:
    class MessageBus:
        def __init__(self, *, bus_type: object) -> None:
            events.append("construct")
            assert bus_type is session
            if constructor_error is not None:
                raise constructor_error

        async def connect(self) -> _Connected:
            return await raw.connect()

        def disconnect(self) -> None:
            raw.disconnect()

    def fake_message(*args: object, **kwargs: object) -> object:
        return object()

    aio = ModuleType("dbus_next.aio")
    aio.MessageBus = MessageBus  # type: ignore[attr-defined]
    dbus_module = ModuleType("dbus_next")
    bus_type_module = ModuleType("FakeBusType")
    bus_type_module.SESSION = session  # type: ignore[attr-defined]
    dbus_module.BusType = bus_type_module  # type: ignore[attr-defined]
    dbus_module.Message = message_factory if message_factory is not None else fake_message  # type: ignore[attr-defined]

    def fake_import(name: str) -> ModuleType:
        events.append(f"import:{name}")
        return {"dbus_next.aio": aio, "dbus_next": dbus_module}[name]

    monkeypatch.setattr(lifecycle_monitor, "import_module", fake_import)


async def test_constructor_failure_has_no_raw_to_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = object()
    events: list[str] = []
    raw = _Raw(events, _Connected())
    original = OSError("fake lifecycle constructor failure")
    _install(monkeypatch, session, raw, events, constructor_error=original)
    with pytest.raises(OSError) as raised:
        await lifecycle_monitor._default_bus_factory()  # pyright: ignore[reportPrivateUsage]
    assert raised.value is original
    assert events == ["import:dbus_next.aio", "import:dbus_next", "construct"]
    assert raw.disconnects == 0


async def test_success_transfers_without_premature_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = object()
    events: list[str] = []
    connected = _Connected()
    raw = _Raw(events, connected)
    _install(monkeypatch, session, raw, events)
    bus = await lifecycle_monitor._default_bus_factory()  # pyright: ignore[reportPrivateUsage]
    assert isinstance(bus, lifecycle_monitor._DbusNextLifecycleBus)  # pyright: ignore[reportPrivateUsage]
    assert events == ["import:dbus_next.aio", "import:dbus_next", "construct", "connect"]
    assert raw.disconnects == 0
    assert connected.disconnects == 0
    assert connected.handlers == []


async def test_connect_error_disconnects_only_raw_and_preserves_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = object()
    events: list[str] = []
    connected = _Connected()
    primary = OSError("fake lifecycle connect failure")
    raw = _Raw(events, connected, error=primary)
    _install(monkeypatch, session, raw, events)
    with pytest.raises(OSError) as raised:
        await lifecycle_monitor._default_bus_factory()  # pyright: ignore[reportPrivateUsage]
    assert raised.value is primary
    assert events[-2:] == ["connect", "disconnect"]
    assert raw.disconnects == 1
    assert connected.disconnects == 0


async def test_cancellation_disconnects_raw_once(monkeypatch: pytest.MonkeyPatch) -> None:
    session = object()
    events: list[str] = []
    entered = asyncio.Event()
    release = asyncio.Event()
    connected = _Connected()

    class BlockingRaw(_Raw):
        async def connect(self) -> _Connected:
            self._events.append("connect")
            entered.set()
            await release.wait()
            raise AssertionError("must be cancelled")

    raw = BlockingRaw(events, connected)
    _install(monkeypatch, session, raw, events)
    task = asyncio.create_task(lifecycle_monitor._default_bus_factory())  # pyright: ignore[reportPrivateUsage]
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel("lifecycle gated connect cancellation")
        with pytest.raises(asyncio.CancelledError) as raised:
            async with asyncio.timeout(2):
                await task
        assert events[-2:] == ["connect", "disconnect"]
        assert raw.disconnects == 1
        assert connected.disconnects == 0
        assert raised.value.args == ("lifecycle gated connect cancellation",)
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=2)


@pytest.mark.parametrize("kind", ["ordinary", "keyboard-interrupt", "system-exit"])
async def test_secondary_disconnect_failure_preserves_primary(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    session = object()
    events: list[str] = []
    connected = _Connected()
    primary: BaseException
    if kind == "ordinary":
        primary = OSError("primary lifecycle connect failure")
    elif kind == "keyboard-interrupt":
        primary = KeyboardInterrupt("injected interrupt")
    else:
        primary = SystemExit(3)
    raw = _Raw(
        events,
        connected,
        error=primary,
        disconnect_error=OSError("secondary disconnect failure"),
    )
    _install(monkeypatch, session, raw, events)
    with pytest.raises(type(primary)) as raised:
        await lifecycle_monitor._default_bus_factory()  # pyright: ignore[reportPrivateUsage]
    assert raised.value is primary
    assert raw.disconnects == 1
    assert connected.disconnects == 0


async def test_wrapper_failure_cleans_connected_raw(monkeypatch: pytest.MonkeyPatch) -> None:
    session = object()
    events: list[str] = []
    connected = _Connected()
    raw = _Raw(events, connected)
    _install(monkeypatch, session, raw, events)
    primary = RuntimeError("fake wrapper failure")

    class FailingWrapper:
        def __init__(self, bus: object, factory: object) -> None:
            raise primary

    monkeypatch.setattr(lifecycle_monitor, "_DbusNextLifecycleBus", FailingWrapper)
    with pytest.raises(RuntimeError) as raised:
        await lifecycle_monitor._default_bus_factory()  # pyright: ignore[reportPrivateUsage]
    assert raised.value is primary
    assert events[-2:] == ["connect", "disconnect"]
    assert raw.disconnects == 1
    assert connected.disconnects == 0


async def test_wrapper_failure_with_secondary_disconnect_preserves_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = object()
    events: list[str] = []
    connected = _Connected()
    primary = RuntimeError("fake wrapper failure")
    raw = _Raw(events, connected, disconnect_error=OSError("secondary disconnect failure"))
    _install(monkeypatch, session, raw, events)

    class FailingWrapper:
        def __init__(self, bus: object, factory: object) -> None:
            raise primary

    monkeypatch.setattr(lifecycle_monitor, "_DbusNextLifecycleBus", FailingWrapper)
    with pytest.raises(RuntimeError) as raised:
        await lifecycle_monitor._default_bus_factory()  # pyright: ignore[reportPrivateUsage]
    assert raised.value is primary
    assert events[-2:] == ["connect", "disconnect"]
    assert raw.disconnects == 1
    assert connected.disconnects == 0
