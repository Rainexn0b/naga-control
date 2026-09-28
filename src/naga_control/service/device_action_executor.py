"""Bounded serialized execution of device-action intents."""

import asyncio
import logging
from collections.abc import Callable
from typing import Protocol

from naga_control.domain.hardware import HardwareScrollMode, HardwareState
from naga_control.domain.intents import DeviceActionIntent

logger = logging.getLogger(__name__)


class ActionHardwareWorker(Protocol):
    async def move_dpi_stage(self, direction: int) -> HardwareState: ...

    async def set_scroll_mode(self, mode: HardwareScrollMode) -> HardwareState: ...

    async def move_scroll_mode(self, direction: int) -> HardwareState: ...


class DeviceActionExecutor:
    """Queue hardware actions from input frames without creating per-event tasks."""

    def __init__(
        self,
        worker: ActionHardwareWorker,
        *,
        queue_size: int = 16,
        on_state: Callable[[HardwareState], None] | None = None,
        on_failure: Callable[[DeviceActionIntent, Exception], None] | None = None,
        on_rejected: Callable[[DeviceActionIntent], None] | None = None,
    ) -> None:
        if queue_size < 1:
            raise ValueError("queue_size must be at least one")
        self._worker = worker
        self._queue: asyncio.Queue[DeviceActionIntent | None] = asyncio.Queue(queue_size)
        self._on_state = on_state
        self._on_failure = on_failure
        self._on_rejected = on_rejected
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    async def start(self) -> None:
        if self._task is None:
            if self._stopping:
                raise RuntimeError("device action executor is stopping")
            self._task = asyncio.create_task(self._run())

    def submit(self, intent: DeviceActionIntent) -> bool:
        if self._task is None or self._stopping or self._queue.full():
            logger.warning(
                "device action rejected (%s): %s", intent.action, self._rejection_reason()
            )
            if self._on_rejected is not None:
                self._on_rejected(intent)
            return False
        self._queue.put_nowait(intent)
        return True

    def _rejection_reason(self) -> str:
        if self._task is None:
            return "executor not running"
        if self._stopping:
            return "executor stopping"
        return "queue full"

    async def stop(self) -> None:
        if self._task is None:
            self._stopping = True
            return
        self._stopping = True
        await self._queue.put(None)
        await self._task
        self._task = None

    async def _run(self) -> None:
        while (intent := await self._queue.get()) is not None:
            try:
                logger.debug("executing device action %s", intent.action)
                state = await _execute(self._worker, intent)
            except Exception as exc:
                logger.exception("device action %s failed", intent.action)
                if self._on_failure is not None:
                    self._on_failure(intent, exc)
            else:
                if self._on_state is not None:
                    self._on_state(state)
            finally:
                self._queue.task_done()
        self._queue.task_done()


async def _execute(worker: ActionHardwareWorker, intent: DeviceActionIntent) -> HardwareState:
    match intent.action:
        case "dpi_stage_up":
            return await worker.move_dpi_stage(1)
        case "dpi_stage_down":
            return await worker.move_dpi_stage(-1)
        case "scroll_mode_next":
            return await worker.move_scroll_mode(1)
        case "scroll_mode_previous":
            return await worker.move_scroll_mode(-1)
        case "scroll_tactile":
            return await worker.set_scroll_mode("tactile")
        case "scroll_precision_tactile":
            return await worker.set_scroll_mode("precision_tactile")
        case "scroll_free_spin":
            return await worker.set_scroll_mode("free_spin")
