"""DEBT-14 exported-method readiness contracts, without a bus or hardware."""

import asyncio
import inspect
import json
import traceback
from collections.abc import Callable, Coroutine
from typing import Protocol, cast

import pytest
from dbus_next.errors import DBusError
from dbus_next.service import ServiceInterface

from naga_control.domain.errors import ConfigValidationError
from naga_control.ipc.service import NagaControlInterface
from naga_control.service.runtime import StaleConfigurationRevisionError, UnknownProfileError

ERROR_PREFIX = "org.nagacontrol.Service1.Error"
UNAVAILABLE_TEXT = "Naga Control service is unavailable."
SNAPSHOT = {"status": "absent", "generation": 0, "error": None}
DOCUMENT = "schema_version = 1\n"
METHODS: dict[str, tuple[tuple[object, ...], str, str, object]] = {
    "GetSnapshot": ((), "", "s", json.dumps(SNAPSHOT, sort_keys=True, separators=(",", ":"))),
    "GetConfiguration": ((), "", "s", DOCUMENT),
    "ReleaseAll": ((), "", "", None),
    "ApplyConfiguration": ((4, DOCUMENT), "qs", "q", 5),
    "SelectProfile": (("alternate",), "s", "q", 6),
    "BeginCalibration": ((), "", "b", True),
    "EndCalibration": ((), "", "b", False),
}


class ExportedMethod(Protocol):
    name: str
    disabled: bool
    in_signature: str
    out_signature: str
    fn: Callable[..., object]


class WireError(Protocol):
    type: str
    text: str


def exported(interface: NagaControlInterface) -> dict[str, ExportedMethod]:
    # The decorator wrapper discards returns; .fn is what dbus-next dispatches.
    get_methods = cast(
        Callable[[ServiceInterface], list[ExportedMethod]],
        ServiceInterface._get_methods,  # pyright: ignore[reportUnknownMemberType, reportPrivateUsage]
    )
    return {item.name: item for item in get_methods(interface) if not item.disabled}


def invoke(interface: NagaControlInterface, name: str) -> Coroutine[object, object, object]:
    fn = exported(interface)[name].fn
    assert inspect.iscoroutinefunction(fn), f"{name} must be an async exported method"
    result = fn(interface, *METHODS[name][0])
    assert inspect.isawaitable(result), f"{name} must return an awaitable"
    return cast(Coroutine[object, object, object], result)


class Service:
    def __init__(self, *, initialized: bool = False) -> None:
        self.initialized = initialized
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.state: dict[str, object] = dict(SNAPSHOT)
        self.error: Exception | None = None

    def record(self, name: str, *args: object) -> None:
        self.calls.append((name, args))
        assert self.initialized, f"{name} reached the uninitialized service"
        if self.error is not None:
            raise self.error

    def snapshot(self) -> dict[str, object]:
        self.record("GetSnapshot")
        return self.state

    def configuration_document(self) -> str:
        self.record("GetConfiguration")
        return DOCUMENT

    def configuration_revision(self) -> int:
        self.record("configuration_revision")
        return 4

    def release_all(self) -> None:
        self.record("ReleaseAll")

    async def apply_configuration(self, expected_revision: int, document: str) -> int:
        self.record("ApplyConfiguration", expected_revision, document)
        return 5

    async def select_profile(self, profile_id: str) -> int:
        self.record("SelectProfile", profile_id)
        return 6

    async def begin_calibration(self) -> bool:
        self.record("BeginCalibration")
        return True

    async def end_calibration(self) -> bool:
        self.record("EndCalibration")
        return False


async def cancel_tasks(tasks: list[asyncio.Task[object]]) -> None:
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def assert_unavailable(error: object) -> None:
    assert isinstance(error, DBusError)
    wire = cast(WireError, error)
    assert wire.type == f"{ERROR_PREFIX}.Unavailable"
    assert wire.text == UNAVAILABLE_TEXT
    assert str(error) == UNAVAILABLE_TEXT


@pytest.mark.parametrize("name", METHODS)
def test_exported_wire_signatures_are_unchanged(name: str) -> None:
    methods = exported(NagaControlInterface(Service()))
    assert set(methods) == set(METHODS)
    assert (methods[name].in_signature, methods[name].out_signature) == METHODS[name][1:3]


@pytest.mark.parametrize("explicit_ready", [False, True], ids=["default", "ready-true"])
@pytest.mark.parametrize("name", METHODS)
async def test_ready_constructor_delegates_exported_calls(name: str, explicit_ready: bool) -> None:
    service = Service(initialized=True)
    interface = (
        NagaControlInterface(service, ready=True)
        if explicit_ready
        else NagaControlInterface(service)
    )
    async with asyncio.timeout(1):
        assert await invoke(interface, name) == METHODS[name][3]
    assert service.calls == [(name, METHODS[name][0])]


@pytest.mark.parametrize("name", METHODS)
async def test_exported_call_waits_without_touching_uninitialized_service(name: str) -> None:
    service = Service()
    interface = NagaControlInterface(service, ready=False)
    task = asyncio.create_task(invoke(interface, name))
    try:
        await asyncio.sleep(0)
        assert not task.done()
        assert service.calls == []
        service.initialized = True
        interface.mark_ready()
        interface.mark_ready()
        async with asyncio.timeout(1):
            assert await task == METHODS[name][3]
            assert await invoke(interface, name) == METHODS[name][3]
        assert service.calls == [(name, METHODS[name][0])] * 2
    finally:
        await cancel_tasks([task])


async def test_unavailable_exported_call_suppresses_active_sensitive_exception() -> None:
    service = Service()
    interface = NagaControlInterface(service, ready=False)
    interface.mark_unavailable()
    secret = "SECRET_SERIAL/USBPATH"
    try:
        raise RuntimeError(secret)
    except RuntimeError:
        with pytest.raises(DBusError) as raised:
            await invoke(interface, "GetSnapshot")
        assert_unavailable(raised.value)
        assert raised.value.__cause__ is None
        assert raised.value.__suppress_context__ is True
        rendered = "".join(traceback.format_exception(raised.value))
        assert all(part not in rendered for part in secret.split("/"))
    assert service.calls == []


async def test_mark_ready_wakes_all_seven_queued_calls() -> None:
    service = Service()
    interface = NagaControlInterface(service, ready=False)
    tasks = [asyncio.create_task(invoke(interface, name)) for name in METHODS]
    try:
        await asyncio.sleep(0)
        assert all(not task.done() for task in tasks)
        assert service.calls == []
        service.initialized = True
        interface.mark_ready()
        async with asyncio.timeout(1):
            assert await asyncio.gather(*tasks) == [spec[3] for spec in METHODS.values()]
        assert sorted(service.calls) == sorted((name, spec[0]) for name, spec in METHODS.items())
    finally:
        await cancel_tasks(tasks)


@pytest.mark.parametrize("name", METHODS)
async def test_cancelling_one_waiter_neither_opens_nor_poisons_other_calls(name: str) -> None:
    service = Service()
    interface = NagaControlInterface(service, ready=False)
    cancelled = asyncio.create_task(invoke(interface, name))
    survivors = [asyncio.create_task(invoke(interface, member)) for member in METHODS]
    try:
        await asyncio.sleep(0)
        cancelled.cancel("fake client disconnected")
        with pytest.raises(asyncio.CancelledError):
            async with asyncio.timeout(1):
                await cancelled
        await asyncio.sleep(0)
        assert all(not task.done() for task in survivors)
        assert service.calls == []
        service.initialized = True
        interface.mark_ready()
        async with asyncio.timeout(1):
            assert await asyncio.gather(*survivors) == [spec[3] for spec in METHODS.values()]
        assert sorted(service.calls) == sorted(
            (member, spec[0]) for member, spec in METHODS.items()
        )
    finally:
        await cancel_tasks([cancelled, *survivors])


@pytest.mark.parametrize("phase", ["startup-failure", "shutdown"])
async def test_unavailable_wakes_every_pending_call_with_fixed_safe_error(phase: str) -> None:
    service = Service()
    interface = NagaControlInterface(service, ready=False)
    tasks = [asyncio.create_task(invoke(interface, name)) for name in METHODS]
    try:
        await asyncio.sleep(0)
        assert all(not task.done() for task in tasks)
        assert service.calls == []
        try:
            raise RuntimeError(f"{phase}: SERIAL_PLACEHOLDER USB_PATH_PLACEHOLDER noRawData")
        except RuntimeError:
            interface.mark_unavailable()
        interface.mark_unavailable()
        interface.mark_ready()
        async with asyncio.timeout(1):
            errors = await asyncio.gather(*tasks, return_exceptions=True)
        for error in errors:
            assert_unavailable(error)
        assert service.calls == []
    finally:
        await cancel_tasks(tasks)


@pytest.mark.parametrize("initial_ready", [False, True])
@pytest.mark.parametrize("name", METHODS)
async def test_terminal_unavailable_blocks_new_queries_and_mutations(
    name: str, initial_ready: bool
) -> None:
    service = Service(initialized=True)
    interface = NagaControlInterface(service, ready=initial_ready)
    interface.mark_unavailable()
    interface.mark_ready()
    interface.mark_unavailable()
    async with asyncio.timeout(1):
        with pytest.raises(DBusError) as raised:
            await invoke(interface, name)
    assert_unavailable(raised.value)
    assert service.calls == []


async def test_unavailable_before_ready_waiters_resume_wins_over_readiness() -> None:
    service = Service()
    interface = NagaControlInterface(service, ready=False)
    tasks = [asyncio.create_task(invoke(interface, name)) for name in METHODS]
    try:
        await asyncio.sleep(0)
        assert all(not task.done() for task in tasks)
        interface.mark_ready()
        interface.mark_unavailable()
        async with asyncio.timeout(1):
            errors = await asyncio.gather(*tasks, return_exceptions=True)
        for error in errors:
            assert_unavailable(error)
        assert service.calls == []
    finally:
        await cancel_tasks(tasks)


@pytest.mark.parametrize("status", ["absent", "unavailable"])
async def test_ready_means_initialized_not_hardware_available(status: str) -> None:
    service = Service(initialized=True)
    service.state["status"] = status
    interface = NagaControlInterface(service, ready=False)
    interface.mark_ready()
    async with asyncio.timeout(1):
        document = await invoke(interface, "GetSnapshot")
    assert isinstance(document, str)
    assert json.loads(document) == service.state
    assert service.calls == [("GetSnapshot", ())]


@pytest.mark.parametrize("terminal", [False, True])
def test_nonexported_synchronous_helpers_are_not_readiness_gated(terminal: bool) -> None:
    service = Service(initialized=True)
    interface = NagaControlInterface(service, ready=False)
    if terminal:
        interface.mark_unavailable()
    assert not inspect.iscoroutinefunction(interface.snapshot_document)
    assert not inspect.iscoroutinefunction(interface.configuration_document)
    assert not inspect.iscoroutinefunction(interface.release_outputs)
    assert json.loads(interface.snapshot_document()) == service.state
    assert interface.configuration_document() == DOCUMENT
    assert interface.release_outputs() is None
    assert service.calls == [("GetSnapshot", ()), ("GetConfiguration", ()), ("ReleaseAll", ())]


@pytest.mark.parametrize("queued", [False, True], ids=["default-ready", "queued"])
@pytest.mark.parametrize(
    ("name", "error", "suffix"),
    [
        ("ApplyConfiguration", StaleConfigurationRevisionError("stale"), "StaleRevision"),
        (
            "ApplyConfiguration",
            ConfigValidationError("profiles", "invalid"),
            "InvalidConfiguration",
        ),
        ("SelectProfile", UnknownProfileError("missing"), "UnknownProfile"),
    ],
)
async def test_ready_exported_calls_preserve_typed_error_translation(
    name: str, error: Exception, suffix: str, queued: bool
) -> None:
    service = Service(initialized=not queued)
    service.error = error
    interface = (
        NagaControlInterface(service, ready=False) if queued else NagaControlInterface(service)
    )
    task = asyncio.create_task(invoke(interface, name))
    try:
        if queued:
            await asyncio.sleep(0)
            assert not task.done()
            assert service.calls == []
            service.initialized = True
            interface.mark_ready()
        async with asyncio.timeout(1):
            with pytest.raises(DBusError) as raised:
                await task
        wire = cast(WireError, raised.value)
        assert wire.type == f"{ERROR_PREFIX}.{suffix}"
        assert wire.text == str(error)
        assert raised.value.__cause__ is error
        assert service.calls == [(name, METHODS[name][0])]
    finally:
        await cancel_tasks([task])
