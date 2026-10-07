"""DEBT-14 public-name reservation races, with no live bus or hardware owners."""

import asyncio
from contextlib import nullcontext

import pytest
from dbus_next.constants import NameFlag, RequestNameReply
from service_reservation_fakes import (
    SECRET,
    Boundary,
    SharedBusSimulator,
    exported_call,
    queued_call,
    running,
    unavailable,
)

from naga_control.ipc.service import NagaControlInterface
from naga_control.service import service_cli


@pytest.mark.parametrize("reply", [RequestNameReply.EXISTS, RequestNameReply.IN_QUEUE])
async def test_duplicate_reservation_never_enters_hardware_or_stops_unattempted_service(
    reply: RequestNameReply,
) -> None:
    boundary = Boundary()
    boundary.bus.reply = reply
    async with running(boundary) as task:
        with pytest.raises(RuntimeError):
            await task
    assert boundary.events == ["connect", "export", "name", "disconnect"]
    assert boundary.bus.flags == NameFlag.DO_NOT_QUEUE
    assert boundary.calls == []


@pytest.mark.parametrize("reply", [RequestNameReply.PRIMARY_OWNER, RequestNameReply.ALREADY_OWNER])
async def test_public_reservation_precedes_hardware_and_opens_gate_only_after_aux_start(
    reply: RequestNameReply,
) -> None:
    boundary = Boundary()
    boundary.bus.reply = reply
    boundary.blocked.update(("service", "aux"))
    async with running(boundary) as task:
        await boundary.entered["service"].wait()
        assert boundary.events == ["connect", "export", "name", "service"]
        assert boundary.bus.flags == NameFlag.DO_NOT_QUEUE
        async with queued_call(boundary) as call:
            assert not call.done() and boundary.calls == []
            boundary.release["service"].set()
            await boundary.entered["aux"].wait()
            assert not call.done() and boundary.calls == []
            assert not boundary.entered["watcher"].is_set()
            assert "watcher-created" not in boundary.events
            boundary.release["aux"].set()
            await boundary.entered["watcher"].wait()
            assert await call == 7
            assert boundary.calls == ["default"]
        boundary.stopped.set()
        await task
    assert boundary.events[-4:] == ["aux-stop", "stop", "resources-clean", "disconnect"]
    assert boundary.bus.interface is not None
    async with asyncio.timeout(2):
        await unavailable(asyncio.create_task(exported_call(boundary.bus.interface)))
    assert boundary.calls == ["default"]


@pytest.mark.parametrize("phase", ["connect", "name", "service", "aux"])
@pytest.mark.parametrize("cancelled", [False, True])
async def test_startup_failure_preserves_primary_and_fails_gate_before_disconnect(
    phase: str,
    cancelled: bool,
) -> None:
    boundary = Boundary()
    boundary.blocked.add(phase)
    if phase in ("service", "aux"):
        boundary.blocked.add("stop")
    primary = RuntimeError(SECRET)
    if not cancelled:
        boundary.errors[phase] = primary
    async with running(boundary) as task:
        await boundary.entered[phase].wait()
        async with queued_call(boundary) if phase != "connect" else nullcontext(None) as call:
            if call is not None:
                assert not call.done() and boundary.calls == []
            if cancelled:
                task.cancel("single startup cancellation")
            else:
                boundary.release[phase].set()
            if phase in ("service", "aux"):
                await boundary.entered["stop"].wait()
                assert boundary.bus.shared.owner is boundary.bus
                assert "disconnect" not in boundary.events
                assert call is not None
                await unavailable(call)
                boundary.release["stop"].set()
            with pytest.raises(asyncio.CancelledError if cancelled else RuntimeError) as raised:
                await task
            assert raised.value is (boundary.interruption if cancelled else primary)
            if call is not None:
                await unavailable(call)
            assert not boundary.entered["watcher"].is_set()
    assert boundary.events[:1] == ["connect"]
    cleanup = (
        (["aux-stop"] if phase == "aux" else [])
        + (["stop", "resources-clean"] if phase in ("service", "aux") else [])
        + ([] if phase == "connect" else ["disconnect"])
    )
    assert (
        boundary.events
        == ["connect"]
        + ([] if phase == "connect" else ["export", "name"])
        + (["service"] if phase in ("service", "aux") else [])
        + (["aux"] if phase == "aux" else [])
        + cleanup
    )
    assert boundary.bus.shared.owner is None
    if boundary.bus.interface is not None:
        async with asyncio.timeout(2):
            await unavailable(asyncio.create_task(exported_call(boundary.bus.interface)))
    assert boundary.calls == []


async def test_uncertain_remote_name_install_cancellation_releases_queued_waiter() -> None:
    boundary = Boundary()
    boundary.blocked.add("name")
    async with running(boundary) as task:
        await boundary.entered["name"].wait()
        assert boundary.bus.shared.owner is boundary.bus
        async with queued_call(boundary) as call:
            assert not call.done() and boundary.calls == []
            task.cancel("cancel withheld name reply")
            with pytest.raises(asyncio.CancelledError) as raised:
                await task
            assert raised.value is boundary.interruption
            await unavailable(call)
    assert boundary.events == ["connect", "export", "name", "disconnect"]
    assert boundary.bus.shared.owner is None and boundary.calls == []
    if boundary.bus.interface is not None:
        async with asyncio.timeout(2):
            await unavailable(asyncio.create_task(exported_call(boundary.bus.interface)))


@pytest.mark.parametrize("phase", ["constructor", "export"])
async def test_interface_failure_before_name_claim_does_not_start_hardware(
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    boundary = Boundary()
    primary = RuntimeError(SECRET)
    if phase == "constructor":

        def fail_interface(service: object, *, ready: bool = True) -> NagaControlInterface:
            boundary.events.append("constructor")
            assert ready is False
            raise primary

        monkeypatch.setattr(service_cli, "NagaControlInterface", fail_interface)
    else:
        boundary.errors[phase] = primary
    async with running(boundary) as task:
        with pytest.raises(RuntimeError) as raised:
            await task
        assert raised.value is primary
    assert boundary.events == ["connect", phase, "disconnect"]
    assert boundary.bus.shared.owner is None and boundary.calls == []
    if boundary.bus.interface is not None:
        async with asyncio.timeout(2):
            await unavailable(asyncio.create_task(exported_call(boundary.bus.interface)))


async def test_reservation_is_held_through_resource_cleanup_and_teardown_gate_is_closed() -> None:
    shared = SharedBusSimulator()
    first = Boundary(shared)
    first.blocked.add("stop")
    async with running(first) as task:
        await first.entered["watcher"].wait()
        first.stopped.set()
        await first.entered["stop"].wait()
        assert shared.owner is first.bus
        assert first.bus.interface is not None
        await unavailable(asyncio.create_task(exported_call(first.bus.interface)))
        duplicate = Boundary(shared)
        async with running(duplicate) as second:
            with pytest.raises(RuntimeError):
                await second
        assert duplicate.events == ["connect", "export", "name", "disconnect"]
        assert shared.owner is first.bus
        first.release["stop"].set()
        await task
    assert first.events[-3:] == ["stop", "resources-clean", "disconnect"]
    assert shared.owner is None
    successor = Boundary(shared)
    async with running(successor) as third:
        await successor.entered["watcher"].wait()
        successor.stopped.set()
        await third


@pytest.mark.parametrize("phase", ["preset", "connect", "name"])
async def test_stop_requested_before_reservation_resolves_prevents_hardware_start(
    phase: str,
) -> None:
    # Models the injected stop event, not OS signal delivery or prompt startup cancellation.
    boundary = Boundary()
    if phase == "preset":
        boundary.stopped.set()
    else:
        boundary.blocked.add(phase)
    async with running(boundary) as task:
        if phase != "preset":
            await boundary.entered[phase].wait()
            boundary.stopped.set()
            boundary.release[phase].set()
        await task
    assert not any(p in boundary.events for p in ("service", "aux", "stop", "aux-stop", "watcher"))
    assert boundary.bus.shared.owner is None and boundary.calls == []
    if boundary.bus.interface is not None:
        async with asyncio.timeout(2):
            await unavailable(asyncio.create_task(exported_call(boundary.bus.interface)))


@pytest.mark.parametrize("phase", ["service", "aux"])
async def test_stop_requested_during_hardware_startup_prevents_later_stage_and_ready_gate(
    phase: str,
) -> None:
    boundary = Boundary()
    boundary.blocked.add(phase)
    async with running(boundary) as task:
        await boundary.entered[phase].wait()
        async with queued_call(boundary) as call:
            assert not call.done() and boundary.calls == []
            boundary.stopped.set()
            boundary.release[phase].set()
            await task
            await unavailable(call)
    assert boundary.events == ["connect", "export", "name", "service"] + (
        ["aux", "aux-stop"] if phase == "aux" else []
    ) + ["stop", "resources-clean", "disconnect"]
    assert "watcher-created" not in boundary.events
    assert boundary.calls == [] and boundary.bus.shared.owner is None
