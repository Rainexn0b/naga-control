"""Bounded, fake-only owners and exported-method calls for reservation tests."""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Protocol, cast

import pytest
from dbus_next.constants import NameFlag, RequestNameReply
from dbus_next.errors import DBusError
from test_service_cli import Service

from naga_control.domain.hardware import HardwareState
from naga_control.ipc.service import BUS_NAME, OBJECT_PATH, NagaControlInterface
from naga_control.service import service_cli

SECRET = "SECRET_SERIAL /private/usb/port"
UNAVAILABLE = "org.nagacontrol.Service1.Error.Unavailable"


class MethodMetadata(Protocol):
    fn: Callable[[NagaControlInterface, str], Awaitable[object]]


async def exported_call(interface: NagaControlInterface) -> object:
    # Invoke the coroutine registered with dbus-next, not its Python helper/wrapper.
    method = vars(type(interface))["SelectProfile"]
    metadata = cast(MethodMetadata, vars(method)["__DBUS_METHOD"])
    return await metadata.fn(interface, "default")


class SharedBusSimulator:
    def __init__(self) -> None:
        self.owner: Bus | None = None


class Boundary(Service):
    def __init__(self, shared: SharedBusSimulator | None = None) -> None:
        super().__init__()
        self.blocked: set[str] = set()
        self.errors: dict[str, RuntimeError] = {}
        self.entered = {
            p: asyncio.Event() for p in ("connect", "name", "service", "aux", "stop", "watcher")
        }
        self.release = {p: asyncio.Event() for p in self.entered}
        self.interruption: asyncio.CancelledError | None = None
        self.stopped = asyncio.Event()
        self.calls: list[str] = []
        self.bus = Bus(self, shared or SharedBusSimulator())

    async def step(self, phase: str) -> None:
        self.events.append(phase)
        self.entered[phase].set()
        try:
            if phase in self.blocked:
                await self.release[phase].wait()
            if phase in self.errors:
                raise self.errors[phase]
        except asyncio.CancelledError as exc:
            self.interruption = exc
            raise

    async def start(self) -> HardwareState:
        await self.step("service")
        return HardwareState("absent", 1)

    async def stop(self) -> None:
        await self.step("stop")
        self.events.append("resources-clean")

    async def select_profile(self, profile_id: str) -> int:
        self.calls.append(profile_id)
        return 7

    async def connect(self) -> "Bus":
        await self.step("connect")
        return self.bus

    def watcher(self) -> Coroutine[None, None, None]:
        self.events.append("watcher-created")
        return self.step("watcher")

    async def run(self) -> None:
        await service_cli.run(
            self,
            install_signal_handler=lambda handled, callback: None,
            stop_event=self.stopped,
            bus_factory=self.connect,
            topology_watcher=self.watcher,
            openrazer_lifecycle=Auxiliary(self),
        )


class Auxiliary:
    def __init__(self, boundary: Boundary) -> None:
        self.boundary = boundary

    async def start(self) -> None:
        await self.boundary.step("aux")

    async def stop(self) -> None:
        self.boundary.events.append("aux-stop")


class Bus:
    def __init__(self, boundary: Boundary, shared: SharedBusSimulator) -> None:
        self.boundary, self.shared = boundary, shared
        self.interface: NagaControlInterface | None = None
        self.reply: RequestNameReply | None = None
        self.flags = NameFlag.NONE

    def export(self, path: str, interface: NagaControlInterface) -> None:
        assert path == OBJECT_PATH
        self.interface = interface
        self.boundary.events.append("export")
        if "export" in self.boundary.errors:
            raise self.boundary.errors["export"]

    async def request_name(self, name: str, flags: NameFlag = NameFlag.NONE) -> object:
        assert name == BUS_NAME
        self.flags = flags
        reply = self.reply or (
            RequestNameReply.EXISTS if self.shared.owner else RequestNameReply.PRIMARY_OWNER
        )
        if reply in (RequestNameReply.PRIMARY_OWNER, RequestNameReply.ALREADY_OWNER):
            self.shared.owner = self  # Remote installation precedes the reply await.
        await self.boundary.step("name")
        return reply

    def disconnect(self) -> None:
        self.boundary.events.append("disconnect")
        if self.shared.owner is self:
            self.shared.owner = None


@asynccontextmanager
async def running(boundary: Boundary) -> AsyncGenerator[asyncio.Task[None]]:
    task = asyncio.create_task(boundary.run())
    try:
        async with asyncio.timeout(2):
            yield task
    finally:
        for release in boundary.release.values():
            release.set()
        boundary.stopped.set()
        if not task.done():
            task.cancel()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=2)


@asynccontextmanager
async def queued_call(boundary: Boundary) -> AsyncGenerator[asyncio.Task[object]]:
    assert boundary.bus.interface is not None, "export must precede hardware startup"
    task = asyncio.create_task(exported_call(boundary.bus.interface))
    try:
        await asyncio.sleep(0)
        yield task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=2)


async def unavailable(task: asyncio.Task[object]) -> None:
    with pytest.raises(DBusError) as raised:
        await task
    assert raised.value.type == UNAVAILABLE  # pyright: ignore[reportUnknownMemberType]
    assert SECRET not in str(raised.value)
    assert raised.value.__cause__ is None
