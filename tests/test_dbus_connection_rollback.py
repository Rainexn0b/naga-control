"""DEBT-15 IPC pre-transfer raw connection rollback using only fakes."""

import asyncio
from types import ModuleType

import pytest

from naga_control.domain.hardware import HardwareState
from naga_control.ipc import server
from naga_control.service import service_cli


class _Connected:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def disconnect(self) -> None:
        self._events.append("connected-disconnect")


class _Raw:
    def __init__(
        self,
        events: list[tuple[str, object]],
        connected: object,
        error: BaseException | None = None,
        disconnect_error: Exception | None = None,
    ) -> None:
        self._events = events
        self._connected = connected
        self._error = error
        self._disconnect_error = disconnect_error
        self.disconnects = 0

    async def connect(self) -> object:
        self._events.append(("connect", None))
        if self._error is not None:
            raise self._error
        return self._connected

    def disconnect(self) -> None:
        self._events.append(("disconnect", None))
        self.disconnects += 1
        if self._disconnect_error is not None:
            raise self._disconnect_error


def _install(
    monkeypatch: pytest.MonkeyPatch,
    session: object,
    raw: _Raw,
    events: list[tuple[str, object]],
    constructor_error: BaseException | None = None,
) -> None:
    box: dict[str, _Raw] = {"raw": raw}

    class MessageBus:
        def __init__(self, *, bus_type: object) -> None:
            events.append(("construct", bus_type))
            assert bus_type is session
            if constructor_error is not None:
                raise constructor_error

        async def connect(self) -> object:
            return await box["raw"].connect()

        def disconnect(self) -> None:
            box["raw"].disconnect()

    aio = ModuleType("dbus_next.aio")
    aio.MessageBus = MessageBus  # type: ignore[attr-defined]
    constants = ModuleType("dbus_next.constants")
    bus_type_module = ModuleType("FakeBusType")
    bus_type_module.SESSION = session  # type: ignore[attr-defined]
    constants.BusType = bus_type_module  # type: ignore[attr-defined]

    def fake_import(name: str) -> ModuleType:
        events.append(("import", name))
        return {"dbus_next.aio": aio, "dbus_next.constants": constants}[name]

    monkeypatch.setattr(server, "import_module", fake_import)


async def test_constructor_failure_has_no_raw_to_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = object()
    events: list[tuple[str, object]] = []
    raw = _Raw(events, _Connected([]))
    original = OSError("fake constructor failure")
    _install(monkeypatch, session, raw, events, constructor_error=original)
    with pytest.raises(OSError) as raised:
        await server.connect_session_bus()
    assert raised.value is original
    assert events == [
        ("import", "dbus_next.aio"),
        ("import", "dbus_next.constants"),
        ("construct", session),
    ]


async def test_success_transfers_without_premature_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = object()
    events: list[tuple[str, object]] = []
    connected_events: list[str] = []
    connected = _Connected(connected_events)
    raw = _Raw(events, connected)
    _install(monkeypatch, session, raw, events)
    assert await server.connect_session_bus() is connected
    assert events == [
        ("import", "dbus_next.aio"),
        ("import", "dbus_next.constants"),
        ("construct", session),
        ("connect", None),
    ]
    assert raw.disconnects == 0
    assert connected_events == []


async def test_connect_error_disconnects_once_and_preserves_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = object()
    events: list[tuple[str, object]] = []
    connected_events: list[str] = []
    primary = OSError("fake connect failure")
    raw = _Raw(events, _Connected(connected_events), error=primary)
    _install(monkeypatch, session, raw, events)
    with pytest.raises(OSError) as raised:
        await server.connect_session_bus()
    assert raised.value is primary
    assert events[-2:] == [("connect", None), ("disconnect", None)]
    assert raw.disconnects == 1
    assert connected_events == []


async def test_connect_cancellation_disconnects_and_preserves_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = object()
    events: list[tuple[str, object]] = []
    entered = asyncio.Event()
    release = asyncio.Event()
    interruptions: list[asyncio.CancelledError] = []

    class BlockingRaw(_Raw):
        async def connect(self) -> object:
            self._events.append(("connect", None))
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError as exc:
                interruptions.append(exc)
                raise
            raise AssertionError("must be cancelled")

    raw = BlockingRaw(events, _Connected([]))
    _install(monkeypatch, session, raw, events)
    task = asyncio.create_task(server.connect_session_bus())
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel("first gated connect cancellation")
        with pytest.raises(asyncio.CancelledError) as raised:
            async with asyncio.timeout(2):
                await task
        assert interruptions == [raised.value]
        assert events[-2:] == [("connect", None), ("disconnect", None)]
        assert raw.disconnects == 1
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
    events: list[tuple[str, object]] = []
    primary: BaseException
    if kind == "ordinary":
        primary = OSError("primary connect failure")
    elif kind == "keyboard-interrupt":
        primary = KeyboardInterrupt("injected interrupt")
    else:
        primary = SystemExit(3)
    raw = _Raw(
        events,
        _Connected([]),
        error=primary,
        disconnect_error=OSError("secondary disconnect failure"),
    )
    _install(monkeypatch, session, raw, events)
    with pytest.raises(type(primary)) as raised:
        await server.connect_session_bus()
    assert raised.value is primary
    assert raw.disconnects == 1


class _CliService:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def start(self) -> HardwareState:
        self._events.append("service-start")
        return HardwareState(status="absent", generation=1)

    async def stop(self) -> None:
        self._events.append("service-stop")

    def snapshot(self) -> dict[str, object]:
        return {"status": "absent"}

    def release_all(self) -> None: ...

    def configuration_document(self) -> str:
        return ""

    def configuration_revision(self) -> int:
        return 0

    async def apply_configuration(self, expected_revision: int, document: str) -> int:
        return 0

    async def select_profile(self, profile_id: str) -> int:
        return 0

    async def begin_calibration(self) -> bool:
        return True

    async def end_calibration(self) -> bool:
        return False


async def test_cli_cancellation_before_factory_return_disposes_raw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = object()
    bus_events: list[tuple[str, object]] = []
    entered = asyncio.Event()
    release = asyncio.Event()
    interruptions: list[asyncio.CancelledError] = []

    class BlockingRaw(_Raw):
        async def connect(self) -> object:
            self._events.append(("connect", None))
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError as exc:
                interruptions.append(exc)
                raise
            raise AssertionError("must be cancelled")

    raw = BlockingRaw(bus_events, _Connected([]))
    _install(monkeypatch, session, raw, bus_events)
    service_events: list[str] = []
    service = _CliService(service_events)
    stopped = asyncio.Event()
    task = asyncio.create_task(
        service_cli.run(
            service,
            install_signal_handler=lambda handled, callback: None,
            stop_event=stopped,
            bus_factory=server.connect_session_bus,
            topology_watcher=None,
            openrazer_lifecycle=None,
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel("cancel before factory return")
        with pytest.raises(asyncio.CancelledError) as raised:
            async with asyncio.timeout(2):
                await task
        assert raised.value.args == ("cancel before factory return",)
        assert interruptions == [raised.value]
        assert service_events == []
        assert raw.disconnects == 1
        assert ("connect", None) in bus_events
        assert ("disconnect", None) in bus_events
    finally:
        release.set()
        stopped.set()
        if not task.done():
            task.cancel()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=2)
