"""Publish the narrow Naga Control contract on the session bus."""

from collections.abc import Awaitable, Callable
from importlib import import_module
from typing import Protocol, cast

from naga_control.ipc.service import BUS_NAME, OBJECT_PATH, NagaControlInterface


class SessionBus(Protocol):
    async def request_name(self, name: str) -> object: ...
    def export(self, path: str, interface: NagaControlInterface) -> None: ...
    def disconnect(self) -> None: ...


class _ConnectableBus(Protocol):
    async def connect(self) -> SessionBus: ...


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
    return await factory(bus_type=bus_type.SESSION).connect()


async def publish_service(bus: SessionBus, interface: NagaControlInterface) -> None:
    await bus.request_name(BUS_NAME)
    bus.export(OBJECT_PATH, interface)
