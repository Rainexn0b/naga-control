"""Own provisional, active, and detached remapping sessions through cleanup."""

import asyncio
import logging
from collections.abc import Callable

from naga_control.service.contracts import RemappingSession

logger = logging.getLogger(__name__)


class SessionLifecycle:
    def __init__(self, fence: Callable[[], None]) -> None:
        self._fence = fence
        self._current: RemappingSession | None = None
        self._detached: RemappingSession | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def current(self) -> RemappingSession | None:
        return self._current

    @property
    def unsafe(self) -> bool:
        task = self._task
        return task is not None and (
            not task.done() or task.cancelled() or task.exception() is not None
        )

    async def start(self, session: RemappingSession) -> None:
        await self.wait()
        if self._current is not None:
            raise RuntimeError("a remapping session is already active")
        self._current = session
        try:
            await session.start()
        except BaseException:
            try:
                await self.stop()
            except Exception as exc:
                logger.error(
                    "input forwarding startup rollback cleanup failed: %s", type(exc).__name__
                )
            raise

    async def stop(self) -> None:
        if (session := self._current) is not None:
            self._fence()
            self._current = None
            self._detached = session
            self._task = asyncio.create_task(session.stop())
            self._task.add_done_callback(self._completed)
        await self.wait()

    def invalidate(self, lock: asyncio.Lock) -> asyncio.Task[None] | None:
        session = self._current
        if session is None:
            return None
        try:
            session.release_all()
        except Exception as exc:
            logger.error("unsafe session output release cleanup failed: %s", type(exc).__name__)

        async def stop_unsafe_session() -> None:
            try:
                async with lock:
                    if self._current is session:
                        await self.stop()
            except Exception as exc:
                logger.error("unsafe session stop cleanup failed: %s", type(exc).__name__)

        return asyncio.create_task(stop_unsafe_session())

    def release_all(self) -> None:
        if self._current is not None:
            self._current.release_all()

    def _completed(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        if (error := task.exception()) is not None:
            logger.error("detached session cleanup failed: %s", type(error).__name__)
        elif task is self._task:
            self._detached = None

    async def wait(self) -> None:
        if self._task is not None:
            await asyncio.shield(self._task)
