"""Ordered asyncio bridge for blocking hardware-port calls."""

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock
from typing import TypeVar, cast

from naga_control.domain.hardware import (
    DeviceMode,
    HardwareScrollMode,
    HardwareState,
    SettingsFailure,
)
from naga_control.domain.profiles import Profile
from naga_control.ports.hardware import HardwareBackend, NagaTopology

_T = TypeVar("_T")


class HardwareQueueFullError(RuntimeError):
    """The service must shed hardware work rather than grow an unbounded queue."""


class StaleHardwareOperationError(RuntimeError):
    """A queued request belonged to a superseded physical topology."""


class HardwareTopologyStaleError(RuntimeError):
    """A lifecycle rescan must replace stale OpenRazer clients before mutation."""


class HardwareWorkerClosedError(RuntimeError):
    """Hardware work was requested after worker shutdown began."""


@dataclass(slots=True)
class _Request:
    generation: int
    operation: Callable[[], object]
    future: asyncio.Future[object]
    is_rescan: bool = False


class HardwareWorker:
    """Run every synchronous backend call on one dedicated worker thread."""

    def __init__(self, backend: HardwareBackend, *, queue_size: int = 16) -> None:
        if queue_size < 1:
            raise ValueError("queue_size must be at least one")
        self._backend = backend
        self._queue: asyncio.Queue[_Request | None] = asyncio.Queue(maxsize=queue_size)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="naga-hardware")
        self._generation_lock = Lock()
        self._generation = 0
        self._topology_stale = False
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    async def start(self) -> None:
        if self._task is not None:
            return
        if self._stopping:
            raise HardwareWorkerClosedError("hardware worker is stopping")
        self._task = asyncio.create_task(self._run())

    def mark_topology_stale(self) -> None:
        """Synchronously fence mutations until a lifecycle rescan completes."""
        self._mark_topology_stale()

    async def rescan(self, connections: tuple[NagaTopology, ...]) -> HardwareState:
        if self._task is None or self._stopping:
            raise HardwareWorkerClosedError("hardware worker is not running")
        generation = self._mark_topology_stale()
        if self._queue.full():
            await self._queue.join()
        return await self._submit(
            generation, lambda: self._backend.rescan(connections), is_rescan=True
        )

    async def refresh_state(self) -> HardwareState:
        return await self._submit_current(self._backend.refresh_state)

    async def read_device_mode(self) -> DeviceMode:
        return await self._submit_current(self._backend.read_device_mode)

    async def set_device_mode(self, mode: DeviceMode) -> DeviceMode:
        return await self._submit_current(lambda: self._backend.set_device_mode(mode))

    async def move_dpi_stage(self, direction: int) -> HardwareState:
        return await self._submit_current(lambda: self._backend.move_dpi_stage(direction))

    async def set_scroll_mode(self, mode: HardwareScrollMode) -> HardwareState:
        return await self._submit_current(lambda: self._backend.set_scroll_mode(mode))

    async def move_scroll_mode(self, direction: int) -> HardwareState:
        return await self._submit_current(lambda: self._backend.move_scroll_mode(direction))

    async def apply_profile_settings(
        self, profile: Profile
    ) -> tuple[HardwareState, tuple[SettingsFailure, ...]]:
        return await self._submit_current(lambda: self._backend.apply_profile_settings(profile))

    async def stop(self) -> None:
        if self._task is None:
            self._stopping = True
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self._executor, self._backend.close)
            self._executor.shutdown(wait=False)
            return
        if not self._stopping:
            self._stopping = True
            self._cancel_pending()
            self._queue.put_nowait(None)
        await self._task
        self._task = None

    async def _submit_current(self, operation: Callable[[], _T]) -> _T:
        with self._generation_lock:
            if self._topology_stale:
                raise HardwareTopologyStaleError("hardware topology rescan is pending")
            generation = self._generation
        return await self._submit(generation, operation)

    async def _submit(
        self, generation: int, operation: Callable[[], _T], *, is_rescan: bool = False
    ) -> _T:
        if self._task is None or self._stopping:
            raise HardwareWorkerClosedError("hardware worker is not running")
        future: asyncio.Future[_T] = asyncio.get_running_loop().create_future()
        request = _Request(generation, operation, cast("asyncio.Future[object]", future), is_rescan)
        try:
            self._queue.put_nowait(request)
        except asyncio.QueueFull as exc:
            raise HardwareQueueFullError("hardware operation queue is full") from exc
        try:
            return await future
        except asyncio.CancelledError:
            future.cancel()
            raise

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while (request := await self._queue.get()) is not None:
            try:
                if request.future.cancelled() or self._stopping:
                    raise HardwareWorkerClosedError("hardware worker is stopping")
                state = await loop.run_in_executor(self._executor, self._execute, request)
            except Exception as exc:
                if not request.future.done():
                    request.future.set_exception(exc)
            else:
                if not request.future.done():
                    request.future.set_result(state)
            finally:
                self._queue.task_done()
        try:
            await loop.run_in_executor(self._executor, self._backend.close)
        finally:
            self._queue.task_done()
            self._executor.shutdown(wait=False)

    def _cancel_pending(self) -> None:
        while not self._queue.empty():
            request = self._queue.get_nowait()
            if request is not None and not request.future.done():
                request.future.set_exception(
                    HardwareWorkerClosedError("hardware worker is stopping")
                )
            self._queue.task_done()

    def _execute(self, request: _Request) -> object:
        with self._generation_lock:
            current_generation = self._generation
        if request.generation != current_generation:
            raise StaleHardwareOperationError("hardware topology changed before this operation ran")
        state = request.operation()
        if request.is_rescan:
            with self._generation_lock:
                if request.generation == self._generation:
                    self._topology_stale = False
        return state

    def _mark_topology_stale(self) -> int:
        with self._generation_lock:
            self._generation += 1
            self._topology_stale = True
            return self._generation
