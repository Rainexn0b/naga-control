import asyncio
from collections.abc import Awaitable
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import cast

import pytest
from test_hardware_worker import FakeBackend

from naga_control.domain.hardware import HardwareState
from naga_control.service.hardware_worker import HardwareWorker, HardwareWorkerClosedError

TIMEOUT = 2


class FailingBackend(FakeBackend):
    def __init__(
        self, *, block_move: bool = False, block_close: bool = False, fail_move: bool = False
    ) -> None:
        super().__init__(block_first_move=block_move)
        self.block_close = block_close
        self.fail_move = fail_move
        self.move_error = RuntimeError("backend move failed")
        self.close_error: RuntimeError | None = None
        self.close_started = Event()
        self.close_release = Event()

    def move_dpi_stage(self, direction: int) -> HardwareState:
        state = super().move_dpi_stage(direction)
        if self.fail_move and self._move_count == 1:
            raise self.move_error
        return state

    def close(self) -> None:
        super().close()
        self.close_started.set()
        if self.block_close:
            assert self.close_release.wait(timeout=5)
        if self.close_error is not None:
            raise self.close_error


def executor_of(worker: HardwareWorker) -> ThreadPoolExecutor:
    return cast(ThreadPoolExecutor, getattr(worker, "_executor", None))


async def bounded[T](call: Awaitable[T]) -> T:
    return await asyncio.wait_for(asyncio.shield(call), timeout=TIMEOUT)


async def entered(event: Event) -> None:
    assert await asyncio.wait_for(asyncio.to_thread(event.wait, TIMEOUT), timeout=TIMEOUT + 1)


async def cleanup(
    worker: HardwareWorker, backend: FailingBackend, *tasks: asyncio.Task[object]
) -> None:
    # Release fake calls even after a red assertion, then join all test-owned work.
    backend.release.set()
    backend.close_release.set()
    runner = cast(asyncio.Task[None] | None, getattr(worker, "_task", None))
    owned: list[asyncio.Task[object]] = list(tasks)
    if runner is not None:
        owned.append(runner)
        if not runner.done():
            owned.append(asyncio.create_task(worker.stop()))
        elif runner.cancelled():
            # A broken stop can strand request futures after losing their runner.
            for task in owned:
                if not task.done():
                    task.cancel()
    try:
        await asyncio.wait_for(
            asyncio.shield(asyncio.gather(*owned, return_exceptions=True)), timeout=TIMEOUT
        )
    finally:
        for task in owned:
            if not task.done():
                task.cancel()
        await asyncio.wait_for(
            asyncio.shield(asyncio.gather(*owned, return_exceptions=True)), timeout=TIMEOUT
        )
        await asyncio.wait_for(
            asyncio.to_thread(executor_of(worker).shutdown, wait=True), timeout=TIMEOUT
        )


async def test_backend_error_reaches_request_future_and_later_requests_still_work() -> None:
    backend = FailingBackend(fail_move=True)
    worker = HardwareWorker(backend)
    await bounded(worker.start())
    try:
        with pytest.raises(RuntimeError) as raised:
            await bounded(worker.move_dpi_stage(1))
        assert raised.value is backend.move_error
        state = await bounded(worker.move_dpi_stage(-1))
        assert state.generation == 2
        await bounded(worker.stop())
        assert backend.calls == ["dpi:1", "dpi:-1", "close"]
    finally:
        await cleanup(worker, backend)


async def test_cancelled_queued_request_never_executes_and_worker_remains_usable() -> None:
    backend = FailingBackend(block_move=True)
    worker = HardwareWorker(backend)
    await bounded(worker.start())
    active = asyncio.create_task(worker.move_dpi_stage(1))
    queued = asyncio.create_task(worker.move_dpi_stage(-1))
    try:
        await entered(backend.started)
        assert not queued.done()
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(queued), timeout=TIMEOUT)
        backend.release.set()
        await asyncio.wait_for(asyncio.shield(active), timeout=TIMEOUT)
        await bounded(worker.refresh_state())
        assert backend.calls == ["dpi:1", "refresh"]
    finally:
        await cleanup(worker, backend, active, queued)


@pytest.mark.parametrize("fail_move", [False, True], ids=["result", "exception"])
async def test_cancelled_in_flight_request_completion_does_not_poison_worker(
    fail_move: bool,
) -> None:
    backend = FailingBackend(block_move=True, fail_move=fail_move)
    worker = HardwareWorker(backend)
    await bounded(worker.start())
    active = asyncio.create_task(worker.move_dpi_stage(1))
    later: asyncio.Task[HardwareState] | None = None
    try:
        await entered(backend.started)
        active.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(active), timeout=TIMEOUT)
        later = asyncio.create_task(worker.move_dpi_stage(-1))
        await asyncio.sleep(0)
        assert not later.done()
        backend.release.set()
        state = await bounded(later)
        assert state.generation == 2
        await bounded(worker.stop())
        assert backend.calls == ["dpi:1", "dpi:-1", "close"]
    finally:
        await cleanup(worker, backend, active, *((later,) if later else ()))


async def test_stop_finishes_active_call_rejects_pending_and_closes_after_completion() -> None:
    backend = FailingBackend(block_move=True)
    worker = HardwareWorker(backend)
    await bounded(worker.start())
    active = asyncio.create_task(worker.move_dpi_stage(1))
    pending: asyncio.Task[HardwareState] | None = None
    stopper: asyncio.Task[None] | None = None
    try:
        await entered(backend.started)
        pending = asyncio.create_task(worker.move_dpi_stage(-1))
        stopper = asyncio.create_task(worker.stop())
        with pytest.raises(HardwareWorkerClosedError):
            await asyncio.wait_for(asyncio.shield(pending), timeout=TIMEOUT)
        assert not stopper.done()
        assert not backend.close_started.is_set()
        with pytest.raises(HardwareWorkerClosedError):
            await bounded(worker.refresh_state())
        backend.release.set()
        await asyncio.wait_for(asyncio.shield(active), timeout=TIMEOUT)
        await asyncio.wait_for(asyncio.shield(stopper), timeout=TIMEOUT)
        queue = cast(asyncio.Queue[object], getattr(worker, "_queue", None))
        await bounded(queue.join())
        assert backend.calls == ["dpi:1", "close"]
    finally:
        await cleanup(
            worker,
            backend,
            active,
            *((pending,) if pending else ()),
            *((stopper,) if stopper else ()),
        )


async def test_cancelling_stop_caller_does_not_cancel_owned_runner_or_active_request() -> None:
    backend = FailingBackend(block_move=True)
    worker = HardwareWorker(backend)
    await bounded(worker.start())
    active = asyncio.create_task(worker.move_dpi_stage(1))
    pending = asyncio.create_task(worker.move_dpi_stage(-1))
    stopper: asyncio.Task[None] | None = None
    try:
        await entered(backend.started)
        stopper = asyncio.create_task(worker.stop())
        with pytest.raises(HardwareWorkerClosedError):
            await asyncio.wait_for(asyncio.shield(pending), timeout=TIMEOUT)
        stopper.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(stopper), timeout=TIMEOUT)
        runner = cast(asyncio.Task[None], getattr(worker, "_task", None))
        assert not runner.done(), "stop caller cancellation killed the owned runner"
        backend.release.set()
        await asyncio.wait_for(asyncio.shield(active), timeout=TIMEOUT)
        await bounded(worker.stop())
        assert backend.calls == ["dpi:1", "close"]
        assert getattr(executor_of(worker), "_shutdown", False) is True
    finally:
        await cleanup(worker, backend, active, pending, *((stopper,) if stopper else ()))


@pytest.mark.parametrize("started", [False, True], ids=["never-started", "started"])
async def test_cancelled_stop_during_close_keeps_cleanup_owned_until_joined(started: bool) -> None:
    backend = FailingBackend(block_close=True)
    worker = HardwareWorker(backend)
    if started:
        await bounded(worker.start())
    stopper = asyncio.create_task(worker.stop())
    joiner: asyncio.Task[None] | None = None
    try:
        await entered(backend.close_started)
        stopper.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(stopper), timeout=TIMEOUT)
        joiner = asyncio.create_task(worker.stop())
        await asyncio.sleep(0)
        assert not joiner.done(), "a second stop must join the still-running backend close"
        with pytest.raises(HardwareWorkerClosedError):
            await bounded(worker.start())
        backend.close_release.set()
        await asyncio.wait_for(asyncio.shield(joiner), timeout=TIMEOUT)
        assert backend.calls == ["close"]
        assert getattr(executor_of(worker), "_shutdown", False) is True
        await bounded(worker.stop())
    finally:
        await cleanup(worker, backend, stopper, *((joiner,) if joiner else ()))


@pytest.mark.parametrize("started", [False, True], ids=["never-started", "started"])
async def test_repeated_stop_is_safe_and_closes_backend_only_once(started: bool) -> None:
    backend = FailingBackend(block_close=True)
    worker = HardwareWorker(backend)
    if started:
        await bounded(worker.start())
        runner = getattr(worker, "_task", None)
        await bounded(worker.start())
        assert getattr(worker, "_task", None) is runner
    stopper = asyncio.create_task(worker.stop())
    try:
        await entered(backend.close_started)
        with pytest.raises(HardwareWorkerClosedError):
            await bounded(worker.start())
        backend.close_release.set()
        await bounded(stopper)
        await bounded(worker.stop())
        await bounded(worker.stop())
        assert backend.calls == ["close"]
        with pytest.raises(HardwareWorkerClosedError):
            await bounded(worker.start())
    finally:
        await cleanup(worker, backend, stopper)


@pytest.mark.parametrize("started", [False, True], ids=["never-started", "started"])
@pytest.mark.parametrize("cancel_waiters", [False, True], ids=["joined", "abandoned"])
async def test_concurrent_stop_owns_one_close_and_retrieves_failure_without_waiters(
    started: bool,
    cancel_waiters: bool,
) -> None:
    backend = FailingBackend(block_close=True)
    backend.close_error = RuntimeError("backend close failed")
    worker = HardwareWorker(backend)
    if started:
        await bounded(worker.start())
    first = asyncio.create_task(worker.stop())
    second: asyncio.Task[None] | None = None
    try:
        await entered(backend.close_started)
        second = asyncio.create_task(worker.stop())
        await asyncio.sleep(0)
        assert not first.done() and not second.done()
        owned = cast(asyncio.Task[None], getattr(worker, "_task", None))
        if cancel_waiters:
            for waiter in (first, second):
                waiter.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await bounded(waiter)
            assert not owned.done()
        backend.close_release.set()
        if cancel_waiters:
            # asyncio.wait observes completion without retrieving the exception itself.
            await bounded(asyncio.wait({owned}))
            assert getattr(owned, "_log_traceback", True) is False
        else:
            for waiter in (first, second):
                with pytest.raises(RuntimeError) as raised:
                    await bounded(waiter)
                assert raised.value is backend.close_error
        assert backend.calls == ["close"]
        assert getattr(executor_of(worker), "_shutdown", False) is True
        await bounded(worker.stop())
    finally:
        await cleanup(worker, backend, first, *((second,) if second else ()))


@pytest.mark.parametrize("started", [False, True], ids=["never-started", "started"])
async def test_close_failure_still_shuts_down_executor_and_balances_queue(started: bool) -> None:
    backend = FailingBackend()
    backend.close_error = RuntimeError("backend close failed")
    worker = HardwareWorker(backend)
    if started:
        await bounded(worker.start())
    try:
        with pytest.raises(RuntimeError) as raised:
            await bounded(worker.stop())
        assert raised.value is backend.close_error
        assert getattr(executor_of(worker), "_shutdown", False) is True
        with pytest.raises(RuntimeError, match="cannot schedule new futures after shutdown"):
            executor_of(worker).submit(lambda: None)
        queue = cast(asyncio.Queue[object], getattr(worker, "_queue", None))
        await bounded(queue.join())
        assert backend.calls == ["close"]
    finally:
        await cleanup(worker, backend)


@pytest.mark.parametrize("started", [False, True], ids=["never-started", "started"])
async def test_stop_after_close_failure_joins_cleanup_without_resubmitting_close(
    started: bool,
) -> None:
    backend = FailingBackend()
    backend.close_error = RuntimeError("backend close failed")
    worker = HardwareWorker(backend)
    if started:
        await bounded(worker.start())
    try:
        with pytest.raises(RuntimeError) as raised:
            await bounded(worker.stop())
        assert raised.value is backend.close_error
        await bounded(worker.stop())
        await bounded(worker.stop())
        assert backend.calls == ["close"]
        assert getattr(executor_of(worker), "_shutdown", False) is True
        with pytest.raises(HardwareWorkerClosedError):
            await bounded(worker.refresh_state())
    finally:
        await cleanup(worker, backend)
