"""Publish the narrow Naga Control contract on the session bus."""

from collections.abc import Awaitable, Callable
from contextlib import suppress
from importlib import import_module
from typing import Protocol, cast

from dbus_next.constants import NameFlag, RequestNameReply

from naga_control.ipc.service import BUS_NAME, OBJECT_PATH, NagaControlInterface


class SessionBus(Protocol):
    async def request_name(self, name: str, flags: NameFlag = NameFlag.NONE) -> object: ...
    def export(self, path: str, interface: NagaControlInterface) -> None: ...
    def disconnect(self) -> None: ...


class _ConnectableBus(Protocol):
    async def connect(self) -> SessionBus: ...
    def disconnect(self) -> None: ...


class _MessageBusFactory(Protocol):
    def __call__(self, *, bus_type: object) -> _ConnectableBus: ...


class _BusType(Protocol):
    SESSION: object


type SessionBusFactory = Callable[[], Awaitable[SessionBus]]


async def connect_session_bus() -> SessionBus:
    aio = import_module("dbus_next.aio")
    constants = import_module("dbus_next.constants")
    factory = cast(_MessageBusFactory, aio.MessageBus)
    bus_type = cast(_BusType, constants.BusType)
    raw = factory(bus_type=bus_type.SESSION)
    try:
        return await raw.connect()
    except BaseException:
        with suppress(Exception):
            raw.disconnect()
        raise


async def publish_service(bus: SessionBus, interface: NagaControlInterface) -> None:
    """Export and reserve the public name; the interface separately gates readiness."""
    bus.export(OBJECT_PATH, interface)
    reply = await bus.request_name(BUS_NAME, NameFlag.DO_NOT_QUEUE)
    if reply not in {RequestNameReply.PRIMARY_OWNER, RequestNameReply.ALREADY_OWNER}:
        raise RuntimeError("Naga Control session bus name is already owned")
