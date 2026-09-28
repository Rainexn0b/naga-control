import asyncio

import pytest

from naga_control.domain.hardware import HardwareState
from naga_control.domain.intents import DeviceActionIntent
from naga_control.service.device_action_executor import DeviceActionExecutor


class FakeWorker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.state = _state()

    async def move_dpi_stage(self, direction: int) -> HardwareState:
        self.calls.append(("dpi", direction))
        return self.state

    async def set_scroll_mode(self, mode: str) -> HardwareState:
        self.calls.append(("scroll", mode))
        return self.state

    async def move_scroll_mode(self, direction: int) -> HardwareState:
        self.calls.append(("move_scroll", direction))
        return self.state


@pytest.mark.asyncio
async def test_executor_runs_actions_in_fifo_order() -> None:
    worker = FakeWorker()
    executor = DeviceActionExecutor(worker)
    await executor.start()

    assert executor.submit(DeviceActionIntent("dpi_stage_up"))
    assert executor.submit(DeviceActionIntent("scroll_free_spin"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await executor.stop()

    assert worker.calls == [("dpi", 1), ("scroll", "free_spin")]


@pytest.mark.asyncio
async def test_full_queue_rejects_without_waiting() -> None:
    rejected: list[DeviceActionIntent] = []
    executor = DeviceActionExecutor(FakeWorker(), queue_size=1, on_rejected=rejected.append)
    await executor.start()

    assert executor.submit(DeviceActionIntent("dpi_stage_up"))
    assert not executor.submit(DeviceActionIntent("dpi_stage_down"))
    await executor.stop()

    assert rejected == [DeviceActionIntent("dpi_stage_down")]


def _state() -> HardwareState:
    return HardwareState("unavailable", generation=0)
