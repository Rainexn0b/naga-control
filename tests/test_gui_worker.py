import asyncio

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
