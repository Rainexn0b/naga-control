"""Fake-only shutdown gate contracts for PrepareShutdown/Exit."""

import asyncio
import inspect
from collections.abc import Callable, Coroutine
from typing import cast

import pytest
from dbus_next.errors import DBusError
from dbus_next.service import ServiceInterface

from naga_control.ipc.service import NagaControlInterface

ERROR_TYPE = "org.nagacontrol.Service1.Error.Unavailable"
ERROR_TEXT = "Naga Control service is unavailable."
SECRET = "SECRET_SERIAL /private/usb/port"


class Service:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def snapshot(self) -> dict[str, object]:
        self.calls.append("snapshot")
        return {"status": "available"}

    def release_all(self) -> None:
        self.calls.append("release")

    def configuration_document(self) -> str:
        return "doc"

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


class MethodMetadata:
    fn: Callable[..., Coroutine[object, object, object]]


class ExportedMethod:
    name: str
    in_signature: str
    out_signature: str


def call(interface: NagaControlInterface, name: str) -> Coroutine[object, object, object]:
    raw = vars(type(interface))[name]
    metadata = cast(MethodMetadata, vars(raw)["__DBUS_METHOD"])
    assert inspect.iscoroutinefunction(metadata.fn)
    result = metadata.fn(interface)
    assert inspect.isawaitable(result)
    return result


def assert_unavailable(error: object) -> None:
    assert isinstance(error, DBusError)
    assert error.type == ERROR_TYPE  # type: ignore[attr-defined]
    assert error.text == ERROR_TEXT  # type: ignore[attr-defined]
    assert str(error) == ERROR_TEXT
    assert SECRET not in str(error)
    assert error.__cause__ is None


def test_new_methods_have_empty_wire_signatures() -> None:
    get_methods = cast(
        Callable[[ServiceInterface], list[ExportedMethod]],
        ServiceInterface._get_methods,  # pyright: ignore[reportUnknownMemberType, reportPrivateUsage]
    )
    found = get_methods(NagaControlInterface(Service()))
    methods = {item.name: item for item in found}
    assert methods["PrepareShutdown"].in_signature == ""
    assert methods["PrepareShutdown"].out_signature == ""
    assert methods["Exit"].in_signature == ""
    assert methods["Exit"].out_signature == ""
    assert len(found) == 9


async def test_shutdown_without_lifecycle_rejects_with_fixed_error() -> None:
    interface = NagaControlInterface(Service())
    with pytest.raises(DBusError) as first:
        await call(interface, "PrepareShutdown")
    assert_unavailable(first.value)
    with pytest.raises(DBusError) as second:
        await call(interface, "Exit")
    assert_unavailable(second.value)
    assert interface.snapshot_document() == '{"status":"available"}'
    assert interface.configuration_document() == "doc"


async def test_exit_before_prepare_is_rejected() -> None:
    calls: list[str] = []
    exited = asyncio.Event()

    async def prepare() -> None:
        calls.append("prepare")

    interface = NagaControlInterface(Service())
    interface.set_shutdown_callbacks(prepare, exited.set)
    with pytest.raises(DBusError) as raised:
        await call(interface, "Exit")
    assert_unavailable(raised.value)
    assert calls == [] and not exited.is_set()


async def test_prepare_success_closes_gate_for_new_application_calls() -> None:
    service = Service()
    exited = asyncio.Event()
    calls: list[str] = []

    async def prepare() -> None:
        calls.append("prepare")

    interface = NagaControlInterface(service)
    interface.set_shutdown_callbacks(prepare, exited.set)
    await call(interface, "PrepareShutdown")
    assert calls == ["prepare"]
    with pytest.raises(DBusError) as raised:
        await call(interface, "GetSnapshot")
    assert_unavailable(raised.value)
    assert service.calls == []
    await call(interface, "PrepareShutdown")
    assert calls == ["prepare"]
    await call(interface, "Exit")
    assert exited.is_set()


async def test_prepare_failure_is_terminal_redacted_and_blocks_exit() -> None:
    calls: list[str] = []
    original = RuntimeError(SECRET)

    async def prepare() -> None:
        calls.append("prepare")
        raise original

    exited = asyncio.Event()
    interface = NagaControlInterface(Service())
    interface.set_shutdown_callbacks(prepare, exited.set)
    with pytest.raises(DBusError) as first:
        await call(interface, "PrepareShutdown")
    assert_unavailable(first.value)
    with pytest.raises(DBusError) as second:
        await call(interface, "PrepareShutdown")
    assert_unavailable(second.value)
    assert calls == ["prepare"]
    with pytest.raises(DBusError) as refused:
        await call(interface, "Exit")
    assert_unavailable(refused.value)
    assert not exited.is_set()


async def test_concurrent_prepare_joins_single_barrier() -> None:
    calls: list[str] = []
    entered = asyncio.Event()
    release = asyncio.Event()

    async def prepare() -> None:
        calls.append("prepare")
        entered.set()
        await release.wait()

    interface = NagaControlInterface(Service())
    interface.set_shutdown_callbacks(prepare, asyncio.Event().set)
    first = asyncio.create_task(call(interface, "PrepareShutdown"))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        second = asyncio.create_task(call(interface, "PrepareShutdown"))
        try:
            await asyncio.sleep(0)
            assert not first.done() and not second.done()
            release.set()
            async with asyncio.timeout(2):
                await first
                await second
        finally:
            if not second.done():
                second.cancel()
            await asyncio.gather(second, return_exceptions=True)
    finally:
        if not first.done():
            first.cancel()
        await asyncio.gather(first, return_exceptions=True)
    assert calls == ["prepare"]


async def test_cancelling_one_prepare_joiner_does_not_abort_barrier() -> None:
    calls: list[str] = []
    entered = asyncio.Event()
    release = asyncio.Event()

    async def prepare() -> None:
        calls.append("prepare")
        entered.set()
        await release.wait()

    interface = NagaControlInterface(Service())
    interface.set_shutdown_callbacks(prepare, asyncio.Event().set)
    first = asyncio.create_task(call(interface, "PrepareShutdown"))
    second = asyncio.create_task(call(interface, "PrepareShutdown"))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        first.cancel("single joiner cancellation")
        with pytest.raises(asyncio.CancelledError):
            await first
        assert not second.done()
        assert calls == ["prepare"]
        release.set()
        async with asyncio.timeout(2):
            await second
    finally:
        for task in (first, second):
            if not task.done():
                task.cancel()
        await asyncio.gather(first, second, return_exceptions=True)
        release.set()
    assert calls == ["prepare"]
    await call(interface, "PrepareShutdown")
    assert calls == ["prepare"]


async def test_prepare_queues_before_ready_without_touching_resources() -> None:
    calls: list[str] = []
    entered = asyncio.Event()
    release = asyncio.Event()

    async def prepare() -> None:
        calls.append("prepare")
        entered.set()
        await release.wait()

    interface = NagaControlInterface(Service(), ready=False)
    interface.set_shutdown_callbacks(prepare, asyncio.Event().set)
    task = asyncio.create_task(call(interface, "PrepareShutdown"))
    try:
        await asyncio.sleep(0)
        assert not task.done() and calls == []
        interface.mark_ready()
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert not task.done() and calls == ["prepare"]
        release.set()
        async with asyncio.timeout(2):
            await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        release.set()
    assert calls == ["prepare"]


async def test_prepare_after_startup_failure_stays_unavailable() -> None:
    async def prepare() -> None:
        pytest.fail("prepare must not run after startup failure")

    interface = NagaControlInterface(Service(), ready=False)
    interface.set_shutdown_callbacks(prepare, asyncio.Event().set)
    interface.mark_unavailable()
    with pytest.raises(DBusError) as raised:
        async with asyncio.timeout(2):
            await call(interface, "PrepareShutdown")
    assert_unavailable(raised.value)
