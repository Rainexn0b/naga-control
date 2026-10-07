"""Background asyncio loop thread so Qt never blocks on D-Bus calls."""

import asyncio
import threading
from collections.abc import Callable, Coroutine
from concurrent.futures import Future
from typing import Any

type CoroFactory = Callable[[], Coroutine[Any, Any, object]]
type Runner = Callable[[CoroFactory], None]


class LoopWorker:
    """Run coroutines on a dedicated loop owned by a daemon thread."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, timeout: float = 5.0) -> None:
        if self.running:
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run_loop, name="naga-gui-service", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError("service worker loop did not start")

    def stop(self, timeout: float = 5.0) -> None:
        thread, self._thread = self._thread, None
        loop, self._loop = self._loop, None
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout)

    def submit(self, coroutine_factory: CoroFactory) -> Future[object]:
        if self._loop is None or not self._loop.is_running():
            raise RuntimeError("service worker loop is not running")
        return asyncio.run_coroutine_threadsafe(coroutine_factory(), self._loop)

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        loop.call_soon(self._ready.set)
        try:
            loop.run_forever()
        finally:
            tasks = asyncio.all_tasks(loop)
            for task in tasks:
                task.cancel()
            if tasks:
                loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
