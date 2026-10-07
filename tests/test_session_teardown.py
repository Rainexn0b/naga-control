import asyncio

import pytest
from test_session_ownership import (
    ProxyFactory,
    Reader,
    Source,
    TrackedActions,
    TrackedOutput,
    Waiter,
    connection,
)

from naga_control.application.remapping import FirstSliceSession, PreparedSource
from naga_control.domain.defaults import default_configuration
from naga_control.domain.profiles import Profile
from naga_control.ports.forwarding import ForwardingProxyFactory, ProxyReadinessWaiter
from naga_control.ports.hardware import DeviceActionSubmitter
from naga_control.ports.output import KeyboardOutput, MouseOutput


def make_session(
    events: list[str],
    construction_error: BaseException | None = None,
) -> tuple[FirstSliceSession, list[Reader], TrackedOutput, TrackedOutput, TrackedActions]:
    readers: list[Reader] = []
    keyboard, mouse = TrackedOutput(events, "keyboard"), TrackedOutput(events, "mouse")
    actions = TrackedActions(events)

    def factory(
        source: PreparedSource,
        profile: Profile,
        keyboard: KeyboardOutput,
        mouse: MouseOutput,
        device_actions: DeviceActionSubmitter,
        proxy_factory: ForwardingProxyFactory,
        readiness_waiter: ProxyReadinessWaiter,
    ) -> Reader:
        if source.node.interface_number == "02" and construction_error is not None:
            raise construction_error
        reader = Reader(source, events)
        readers.append(reader)
        return reader

    session = FirstSliceSession(
        connection(),
        default_configuration().profile("default"),
        keyboard,
        mouse,
        actions,
        lambda node: Source(node, events),
        ProxyFactory(events),
        Waiter(events),
        factory,
    )
    return session, readers, keyboard, mouse, actions


CLEANUP = (
    "reader.stop:00",
    "reader.stop:01",
    "reader.stop:02",
    "keyboard.release",
    "mouse.release",
    "keyboard.close",
    "mouse.close",
    "actions.stop",
)


@pytest.mark.parametrize("failures", [(name,) for name in CLEANUP] + [CLEANUP, CLEANUP[3:]])
async def test_teardown_attempts_independent_resources_and_preserves_first_error(
    failures: tuple[str, ...],
) -> None:
    events: list[str] = []
    session, readers, keyboard, mouse, actions = make_session(events)
    await session.start()
    errors = {name: RuntimeError(name) for name in failures}
    for reader in readers:
        reader.stop_error = errors.get(f"reader.stop:{reader.source.node.interface_number}")
    for output in (keyboard, mouse):
        output.errors = {
            phase: errors[f"{output.name}.{phase}"]
            for phase in ("release", "close")
            if f"{output.name}.{phase}" in errors
        }
    actions.error = errors.get("actions.stop")
    try:
        with pytest.raises(RuntimeError) as raised:
            async with asyncio.timeout(2):
                await session.stop()
        assert raised.value is errors[failures[0]]
        assert all(events.count(name) == 1 for name in CLEANUP)
        assert all(reader.stopped for reader in readers)
        assert keyboard.closed and mouse.closed and not session.running
        before = list(events)
        # A completed cleanup must never attempt destruction again. Whether the
        # cached error is rethrown on later calls is not part of this contract.
        await asyncio.wait_for(asyncio.gather(session.stop(), return_exceptions=True), 2)
        assert events == before
    finally:
        await asyncio.wait_for(asyncio.gather(session.stop(), return_exceptions=True), 2)


@pytest.mark.parametrize("failure", ["reader", "keyboard.release", "mouse.close", "actions"])
@pytest.mark.parametrize("kind", [RuntimeError, asyncio.CancelledError, KeyboardInterrupt])
@pytest.mark.parametrize("phase", ["factory", "start"])
async def test_activation_failure_is_not_replaced_by_secondary_teardown_error(
    failure: str,
    kind: type[BaseException],
    phase: str,
) -> None:
    events: list[str] = []
    primary, secondary = kind("activation"), OSError("cleanup")
    session, readers, keyboard, mouse, actions = make_session(
        events,
        primary if phase == "factory" else None,
    )
    # Stop errors are installed before a later reader fails activation.
    original_start = Reader.start

    def start(reader: Reader) -> None:
        if reader.source.node.interface_number == "02":
            reader.start_error = primary
        if failure == "reader" and reader.source.node.interface_number == "00":
            reader.stop_error = secondary
        original_start(reader)

    if failure == "keyboard.release":
        keyboard.errors["release"] = secondary
    elif failure == "mouse.close":
        mouse.errors["close"] = secondary
    elif failure == "actions":
        actions.error = secondary
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Reader, "start", start)
        try:
            with pytest.raises(kind) as raised:
                async with asyncio.timeout(2):
                    await session.start()
            assert raised.value is primary
            expected = (
                CLEANUP
                if phase == "start"
                else tuple(name for name in CLEANUP if name != "reader.stop:02")
            )
            assert all(events.count(name) == 1 for name in expected)
            assert "source.close:02" in events
            assert all(reader.stopped for reader in readers)
            assert not session.running
        finally:
            await asyncio.wait_for(asyncio.gather(session.stop(), return_exceptions=True), 2)


async def test_concurrent_stop_joins_owned_cleanup_until_actions_finish() -> None:
    events: list[str] = []
    session, _, _, _, actions = make_session(events)
    actions.block = True
    baseline = asyncio.all_tasks()
    await session.start()
    first = asyncio.create_task(session.stop())
    second: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(actions.stopping.wait(), 2)
        second = asyncio.create_task(session.stop())
        await asyncio.sleep(0)
        assert not first.done() and not second.done()
        assert events.count("actions.stop") == 1
        actions.release.set()
        await asyncio.wait_for(asyncio.gather(first, second), 2)
        assert events.count("actions.stopped") == 1
        await asyncio.wait_for(session.stop(), 2)
        assert all(events.count(name) == 1 for name in CLEANUP)
        assert not (asyncio.all_tasks() - baseline)
    finally:
        actions.release.set()
        tasks = [first] if second is None else [first, second]
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 2)
        await asyncio.wait_for(asyncio.gather(session.stop(), return_exceptions=True), 2)


async def test_cancelled_stopper_leaves_cleanup_running_or_joinable() -> None:
    events: list[str] = []
    session, _, _, _, actions = make_session(events)
    actions.block = True
    baseline = asyncio.all_tasks()
    await session.start()
    stopper = asyncio.create_task(session.stop())
    joiner: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(actions.stopping.wait(), 2)
        stopper.cancel("caller no longer waits")
        await asyncio.sleep(0)
        joiner = asyncio.create_task(session.stop())
        await asyncio.sleep(0)
        assert not joiner.done()
        actions.release.set()
        result = await asyncio.wait_for(asyncio.gather(stopper, return_exceptions=True), 2)
        assert result[0] is None or isinstance(result[0], asyncio.CancelledError)
        await asyncio.wait_for(joiner, 2)
        assert events.count("actions.stopped") == 1
        assert all(events.count(name) == 1 for name in CLEANUP)
        assert not session.running
        assert not (asyncio.all_tasks() - baseline)
    finally:
        actions.release.set()
        tasks = [stopper] if joiner is None else [stopper, joiner]
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 2)
        await asyncio.wait_for(asyncio.gather(session.stop(), return_exceptions=True), 2)
