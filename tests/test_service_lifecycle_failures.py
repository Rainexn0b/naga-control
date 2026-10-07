import asyncio
from typing import NoReturn, cast

import pytest
from test_service_mode import Session, Worker, connection
from test_session_ownership import ProxyFactory, TrackedActions, TrackedOutput, Waiter

from naga_control.application import service_factory
from naga_control.domain.defaults import default_configuration
from naga_control.domain.hardware import HardwareState
from naga_control.ports.hardware import NagaTopology
from naga_control.service.hardware_worker import HardwareWorker
from naga_control.service.runtime import NagaService


class FailingWorker(Worker):
    def __init__(self, events: list[str]) -> None:
        super().__init__(events)
        self.failure: BaseException | None = None
        self.stop_error: Exception | None = None

    async def rescan(self, connections: tuple[NagaTopology, ...]) -> HardwareState:
        state = await super().rescan(connections)
        if self.failure is not None:
            raise self.failure
        return state

    async def stop(self) -> None:
        await super().stop()
        if self.stop_error is not None:
            raise self.stop_error


class FailingSession(Session):
    def __init__(self, events: list[str]) -> None:
        super().__init__(events)
        self.failure: BaseException | None = None
        self.stop_error: Exception | None = None
        self.starting, self.start_gate = asyncio.Event(), asyncio.Event()
        self.block_start = False

    async def start(self) -> None:
        await super().start()
        self.starting.set()
        if self.block_start:
            await self.start_gate.wait()
        if self.failure is not None:
            raise self.failure

    async def stop(self) -> None:
        await super().stop()
        self.events.append("session.stopped")
        if self.stop_error is not None:
            raise self.stop_error


def make_service(worker: FailingWorker, session: FailingSession) -> NagaService:
    return NagaService(
        lambda: (connection(),),
        default_configuration,
        worker,
        lambda _connection, _configuration: session,
    )


@pytest.mark.parametrize("phase", ["rescan", "session"])
@pytest.mark.parametrize("kind", [RuntimeError, asyncio.CancelledError])
@pytest.mark.parametrize("cleanup_error", [False, True])
async def test_startup_rollback_preserves_primary_failure_and_stops_worker(
    phase: str,
    kind: type[BaseException],
    cleanup_error: bool,
) -> None:
    events: list[str] = []
    worker, session = FailingWorker(events), FailingSession(events)
    primary = kind("startup failed")
    if phase == "rescan":
        worker.failure = primary
    else:
        session.failure = primary
    if cleanup_error:
        worker.stop_error = OSError("worker cleanup failed")
        if phase == "session":
            session.stop_error = ValueError("session cleanup failed")
    service = make_service(worker, session)
    baseline = asyncio.all_tasks()
    try:
        with pytest.raises(kind) as raised:
            async with asyncio.timeout(2):
                await service.start()
        assert raised.value is primary
        assert events.count("worker.stop") == 1
        if phase == "session":
            assert events.count("session.stop") == 1
            assert events.index("session.stop") < events.index("worker.stop")
            assert service.snapshot()["mode_ready"] is False
        else:
            assert "session.start" not in events
        assert not (asyncio.all_tasks() - baseline)
        before = list(events)
        await asyncio.wait_for(asyncio.gather(service.stop(), return_exceptions=True), 2)
        assert events == before
    finally:
        await asyncio.wait_for(asyncio.gather(service.stop(), return_exceptions=True), 2)


@pytest.mark.parametrize("phase", ["rescan", "session"])
async def test_caller_cancellation_during_startup_joins_cleanup(phase: str) -> None:
    events: list[str] = []
    worker, session = FailingWorker(events), FailingSession(events)
    if phase == "rescan":
        worker.rescan_gate = asyncio.Event()
        entered = worker.rescan_entered
    else:
        session.block_start = True
        entered = session.starting
    worker.stop_error = OSError("secondary worker failure")
    session.stop_error = ValueError("secondary session failure")
    service = make_service(worker, session)
    baseline = asyncio.all_tasks()
    startup = asyncio.create_task(service.start())
    try:
        await asyncio.wait_for(entered.wait(), 2)
        startup.cancel("startup interrupted")
        with pytest.raises(asyncio.CancelledError) as raised:
            async with asyncio.timeout(2):
                await startup
        assert raised.value.args == ("startup interrupted",)
        assert events.count("worker.stop") == 1
        if phase == "session":
            assert events.count("session.stop") == 1
        assert not (asyncio.all_tasks() - baseline)
    finally:
        session.start_gate.set()
        if worker.rescan_gate is not None:
            worker.rescan_gate.set()
        if not startup.done():
            startup.cancel()
        await asyncio.wait_for(asyncio.gather(startup, return_exceptions=True), 2)
        await asyncio.wait_for(asyncio.gather(service.stop(), return_exceptions=True), 2)


@pytest.mark.parametrize("failure", ["session", "worker", "both", "poll"])
async def test_stop_failure_still_joins_poll_and_attempts_all_owners(
    failure: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    worker, session = FailingWorker(events), FailingSession(events)
    service = make_service(worker, session)
    entered, release = asyncio.Event(), asyncio.Event()
    poll_error = RuntimeError("poll failed")
    session_error, worker_error = ValueError("session failed"), OSError("worker failed")

    async def poll() -> None:
        entered.set()
        try:
            await release.wait()
            raise poll_error
        finally:
            events.append("poll.finished")

    monkeypatch.setattr(service, "_poll_observed_state", poll)
    baseline = asyncio.all_tasks()
    try:
        await asyncio.wait_for(service.start(), 2)
        await asyncio.wait_for(entered.wait(), 2)
        tasks = asyncio.all_tasks() - baseline
        assert len(tasks) == 1
        if failure == "poll":
            release.set()
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 2)
            primary = poll_error
            # A failed poll must not prevent cleanup even when cleanup also fails.
            session.stop_error, worker.stop_error = session_error, worker_error
        else:
            if failure in ("session", "both"):
                session.stop_error = session_error
            if failure in ("worker", "both"):
                worker.stop_error = worker_error
            primary = session_error if failure != "worker" else worker_error
        with pytest.raises(type(primary)) as raised:
            async with asyncio.timeout(2):
                await service.stop()
        assert raised.value is primary
        assert events.count("poll.finished") == 1
        assert events.count("session.stop") == events.count("worker.stop") == 1
        assert events.index("poll.finished") < events.index("session.stop")
        assert all(task.done() for task in tasks)
        assert not (asyncio.all_tasks() - baseline)
        before = list(events)
        await asyncio.wait_for(asyncio.gather(service.stop(), return_exceptions=True), 2)
        assert events == before
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(service.stop(), return_exceptions=True), 2)
        remaining = asyncio.all_tasks() - baseline
        for task in remaining:
            task.cancel()
        await asyncio.wait_for(asyncio.gather(*remaining, return_exceptions=True), 2)


@pytest.mark.parametrize("cancel_caller", [False, True], ids=["concurrent", "cancelled"])
async def test_service_stop_joins_session_cleanup_without_orphans(cancel_caller: bool) -> None:
    events: list[str] = []
    worker, session = FailingWorker(events), FailingSession(events)
    gate = asyncio.Event()
    session.stop_gate = gate
    service = make_service(worker, session)
    baseline = asyncio.all_tasks()
    await asyncio.wait_for(service.start(), 2)
    first = asyncio.create_task(service.stop())
    second: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(session.stopping.wait(), 2)
        if cancel_caller:
            first.cancel("stop caller interrupted")
            await asyncio.sleep(0)
        second = asyncio.create_task(service.stop())
        await asyncio.sleep(0)
        assert not second.done()
        assert "worker.stop" not in events
        gate.set()
        results = await asyncio.wait_for(asyncio.gather(first, second, return_exceptions=True), 2)
        assert results[1] is None
        assert results[0] is None or (
            cancel_caller and isinstance(results[0], asyncio.CancelledError)
        )
        assert events.count("session.stopped") == events.count("worker.stop") == 1
        assert events.index("session.stopped") < events.index("worker.stop")
        before = list(events)
        await asyncio.wait_for(service.stop(), 2)
        assert events == before
        assert not (asyncio.all_tasks() - baseline)
    finally:
        gate.set()
        tasks = [first] if second is None else [first, second]
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 2)
        await asyncio.wait_for(asyncio.gather(service.stop(), return_exceptions=True), 2)


@pytest.mark.parametrize("phase", ["mouse", "actions", "proxy", "readiness"])
@pytest.mark.parametrize("close_error", [False, True])
def test_session_factory_failure_closes_already_owned_outputs_and_preserves_primary(
    phase: str,
    close_error: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    keyboard, mouse = TrackedOutput(events, "keyboard"), TrackedOutput(events, "mouse")
    actions = TrackedActions(events)
    primary = RuntimeError(f"{phase} construction failed")
    if close_error:
        keyboard.errors["close"] = OSError("keyboard close failed")

    def create_mouse() -> TrackedOutput:
        events.append("mouse.create")
        if phase == "mouse":
            raise primary
        return mouse

    def create_actions(*args: object, **kwargs: object) -> TrackedActions:
        if phase == "actions":
            raise primary
        return actions

    def create_proxy() -> ProxyFactory:
        if phase == "proxy":
            raise primary
        return ProxyFactory(events)

    def create_waiter() -> Waiter:
        if phase == "readiness":
            raise primary
        return Waiter(events)

    monkeypatch.setattr(service_factory, "create_virtual_keyboard", lambda: keyboard)
    monkeypatch.setattr(service_factory, "create_virtual_mouse", create_mouse)
    monkeypatch.setattr(service_factory, "DeviceActionExecutor", create_actions)
    monkeypatch.setattr(service_factory, "UInputForwardingProxyFactory", create_proxy)
    monkeypatch.setattr(service_factory, "create_proxy_readiness_waiter", create_waiter)
    factory = service_factory.create_session_factory(cast(HardwareWorker, Worker(events)))
    with pytest.raises(RuntimeError) as raised:
        factory(connection(), default_configuration())
    assert raised.value is primary
    assert events.count("keyboard.close") == 1
    assert keyboard.closed
    if phase != "mouse":
        assert events.count("mouse.close") == 1
        assert mouse.closed
    else:
        assert "mouse.close" not in events


def test_session_factory_validates_profile_before_creating_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    configuration = default_configuration()
    primary = ValueError("profile validation failed")

    def profile(self: object, identifier: str) -> NoReturn:
        assert self is configuration and identifier == configuration.active_profile
        events.append("profile")
        raise primary

    def create_output() -> NoReturn:
        events.append("output.create")
        raise AssertionError("profile validation must precede output creation")

    monkeypatch.setattr(type(configuration), "profile", profile)
    monkeypatch.setattr(service_factory, "create_virtual_keyboard", create_output)
    monkeypatch.setattr(service_factory, "create_virtual_mouse", create_output)
    factory = service_factory.create_session_factory(cast(HardwareWorker, Worker(events)))
    with pytest.raises(ValueError) as raised:
        factory(connection(), configuration)
    assert raised.value is primary
    assert events == ["profile"]
