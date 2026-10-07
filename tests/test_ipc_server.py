"""Session-bus construction and publication contracts using only fake connections."""

import asyncio
from types import ModuleType

import pytest
from dbus_next.constants import NameFlag, RequestNameReply
from test_service_cli import Service

from naga_control.ipc import server
from naga_control.ipc.service import BUS_NAME, OBJECT_PATH, NagaControlInterface


class Bus:
    def __init__(self, reply: RequestNameReply = RequestNameReply.PRIMARY_OWNER) -> None:
        self.reply = reply
        self.events: list[tuple[str, object]] = []
        self.flags = NameFlag.NONE
        self.export_error: Exception | None = None
        self.name_error: Exception | None = None
        self.incumbent = object()
        self.owner = self.incumbent

    def export(self, path: str, interface: NagaControlInterface) -> None:
        self.events.append(("export", (path, interface)))
        if self.export_error is not None:
            raise self.export_error

    async def request_name(self, name: str, flags: NameFlag = NameFlag.NONE) -> object:
        self.events.append(("name", name))
        self.flags = flags
        if flags & NameFlag.REPLACE_EXISTING:
            self.owner = self
        if self.name_error is not None:
            raise self.name_error
        return self.reply

    def disconnect(self) -> None:
        self.events.append(("disconnect", None))


@pytest.mark.parametrize("failure", [None, "constructor", "connect"])
async def test_connect_imports_default_session_bus_without_contacting_dbus(
    monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    bus = Bus()
    session = object()
    original = OSError("fake bus construction/connection failure")
    events: list[tuple[str, object]] = []

    class MessageBus:
        def __init__(self, *, bus_type: object) -> None:
            events.append(("construct", bus_type))
            if failure == "constructor":
                raise original

        async def connect(self) -> Bus:
            events.append(("connect", None))
            if failure == "connect":
                raise original
            return bus

    aio = ModuleType("dbus_next.aio")
    aio.MessageBus = MessageBus  # type: ignore[attr-defined]
    constants = ModuleType("dbus_next.constants")
    bus_type = ModuleType("FakeBusType")
    bus_type.SESSION = session  # type: ignore[attr-defined]
    constants.BusType = bus_type  # type: ignore[attr-defined]

    def fake_import(name: str) -> ModuleType:
        events.append(("import", name))
        return {"dbus_next.aio": aio, "dbus_next.constants": constants}[name]

    monkeypatch.setattr(server, "import_module", fake_import)
    if failure is None:
        assert await server.connect_session_bus() is bus
    else:
        with pytest.raises(OSError) as raised:
            await server.connect_session_bus()
        assert raised.value is original
    assert events == [
        ("import", "dbus_next.aio"),
        ("import", "dbus_next.constants"),
        ("construct", session),
    ] + ([] if failure == "constructor" else [("connect", None)])
    assert bus.events == []


async def test_connect_preserves_in_flight_cancellation_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    interruptions: list[asyncio.CancelledError] = []
    session = object()

    class MessageBus:
        def __init__(self, *, bus_type: object) -> None:
            assert bus_type is session

        async def connect(self) -> Bus:
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError as exc:
                interruptions.append(exc)
                raise
            pytest.fail("fake connect must be cancelled before returning ownership")

    aio = ModuleType("dbus_next.aio")
    aio.MessageBus = MessageBus  # type: ignore[attr-defined]
    constants = ModuleType("dbus_next.constants")
    bus_type = ModuleType("FakeBusType")
    bus_type.SESSION = session  # type: ignore[attr-defined]
    constants.BusType = bus_type  # type: ignore[attr-defined]

    def fake_import(name: str) -> ModuleType:
        return {"dbus_next.aio": aio, "dbus_next.constants": constants}[name]

    monkeypatch.setattr(server, "import_module", fake_import)
    task = asyncio.create_task(server.connect_session_bus())
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel("single fake connect cancellation")
        with pytest.raises(asyncio.CancelledError) as raised:
            async with asyncio.timeout(2):
                await task
        assert interruptions == [raised.value]
        assert raised.value.args == ("single fake connect cancellation",)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=2)


@pytest.mark.parametrize("reply", [RequestNameReply.PRIMARY_OWNER, RequestNameReply.ALREADY_OWNER])
async def test_publish_exports_interface_before_acquiring_name(reply: RequestNameReply) -> None:
    bus = Bus(reply)
    interface = NagaControlInterface(Service())
    await server.publish_service(bus, interface)
    assert bus.events == [("export", (OBJECT_PATH, interface)), ("name", BUS_NAME)]
    assert bus.flags & NameFlag.DO_NOT_QUEUE
    assert not bus.flags & NameFlag.REPLACE_EXISTING


@pytest.mark.parametrize("reply", [RequestNameReply.EXISTS, RequestNameReply.IN_QUEUE])
async def test_publish_rejects_duplicate_owner_without_stealing_or_queueing(
    reply: RequestNameReply,
) -> None:
    bus = Bus(reply)
    interface = NagaControlInterface(Service())
    with pytest.raises(RuntimeError):
        await server.publish_service(bus, interface)
    assert bus.events == [("export", (OBJECT_PATH, interface)), ("name", BUS_NAME)]
    assert bus.owner is bus.incumbent
    assert bus.flags & NameFlag.DO_NOT_QUEUE
    assert not bus.flags & NameFlag.REPLACE_EXISTING


@pytest.mark.parametrize("phase", ["export", "name"])
async def test_publish_preserves_boundary_failure_and_does_not_acquire_before_export(
    phase: str,
) -> None:
    bus = Bus()
    original = OSError(f"fake {phase} failure")
    if phase == "export":
        bus.export_error = original
    else:
        bus.name_error = original
    interface = NagaControlInterface(Service())
    with pytest.raises(OSError) as raised:
        await server.publish_service(bus, interface)
    assert raised.value is original
    assert bus.events == [("export", (OBJECT_PATH, interface))] + (
        [("name", BUS_NAME)] if phase == "name" else []
    )
