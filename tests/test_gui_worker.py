import asyncio
import threading

import pytest

from naga_control.gui.worker import LoopWorker


def test_worker_runs_coroutines_and_stops_cleanly() -> None:
    worker = LoopWorker()
    worker.start()

    assert worker.running

    async def value() -> int:
        await asyncio.sleep(0.01)
        return 42

    future = worker.submit(value)
    assert future.result(timeout=5) == 42

    async def failing() -> None:
        raise RuntimeError("boom")

    failure = worker.submit(failing)
    with pytest.raises(RuntimeError, match="boom"):
        failure.result(timeout=5)

    worker.stop(timeout=5)

    assert not worker.running


def test_submit_rejects_a_stopped_worker() -> None:
    worker = LoopWorker()

    async def nothing() -> None:
        return None

    try:
        worker.submit(nothing)
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass


def test_shutdown_cancels_pending_coroutines_and_worker_can_restart() -> None:
    worker = LoopWorker()
    worker.start()
    started, cleaned = threading.Event(), threading.Event()

    async def pending() -> None:
        started.set()
        try:
            await asyncio.sleep(3600)
        finally:
            cleaned.set()

    future = worker.submit(pending)
    assert started.wait(5)
    worker.stop(timeout=1)
    assert cleaned.is_set()
    assert future.cancelled()
    worker.start()

    async def value() -> int:
        return 42

    assert worker.submit(value).result(timeout=5) == 42
    worker.stop()
