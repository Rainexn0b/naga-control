"""Owned asyncio readiness for evdev descriptors.

The iterator registers one loop.add_reader callback that only signals an
owned asyncio.Event. The reading coroutine performs the existing nonblocking
device.read call itself, so no Future done-callback consumes a lazy batch
after close. Exactly one active iterator exists per guard, with no task per
event and no retained upstream futures.
"""

import asyncio
from collections.abc import AsyncGenerator, Callable, Iterator


class OwnedEvdevReadiness[T]:
    """Own a single loop.add_reader registration for one physical fd."""

    def __init__(
        self,
        get_fd: Callable[[], int],
        do_read: Callable[[], Iterator[T]],
    ) -> None:
        self._get_fd = get_fd
        self._do_read = do_read
        self._loop: asyncio.AbstractEventLoop | None = None
        self._fd: int | None = None
        self._ready: asyncio.Event | None = None
        self._registered = False
        self._generation = 0
        self._closed = False
        self._active = False
        self._detach_error: Exception | None = None

    @property
    def detach_error(self) -> Exception | None:
        """First ordinary detach failure, if any, with exact identity."""
        return self._detach_error

    def _note_detach_error(self, exc: Exception) -> None:
        if self._detach_error is None:
            self._detach_error = exc

    def request_close(self) -> None:
        """Retire synchronously and unregister before the device is closed."""
        if self._detach_error is not None:
            raise self._detach_error
        was_registered = self._registered
        loop = self._loop
        fd = self._fd
        ready = self._ready
        self._generation += 1
        self._registered = False
        self._closed = True
        self._loop = None
        self._fd = None
        self._ready = None
        if ready is not None:
            ready.set()
        if not was_registered:
            return
        if loop is None or fd is None:
            return
        try:
            closed = loop.is_closed()
        except Exception as exc:
            self._note_detach_error(exc)
            raise
        if closed:
            return
        try:
            loop.remove_reader(fd)
        except Exception as exc:
            self._note_detach_error(exc)
            raise

    def iterate(self) -> AsyncGenerator[T, None]:
        """Return the single active async iterator for this guard."""
        return self._run()

    async def _run(self) -> AsyncGenerator[T, None]:
        if self._closed:
            return
        if self._detach_error is not None:
            raise self._detach_error
        if self._active:
            raise RuntimeError("evdev async reader is already active")
        self._active = True
        generation = self._generation
        try:
            loop = asyncio.get_running_loop()
            if loop.is_closed():
                return
            fd = self._get_fd()
            ready = asyncio.Event()
            self._loop = loop
            self._fd = fd
            self._ready = ready
            self._registered = True

            def _on_ready(
                captured_generation: int = generation,
                captured_ready: asyncio.Event = ready,
            ) -> None:
                if captured_generation != self._generation:
                    return
                if not self._registered:
                    return
                if self._closed:
                    return
                captured_ready.set()

            try:
                loop.add_reader(fd, _on_ready)
            except Exception:
                self._registered = False
                self._loop = None
                self._fd = None
                self._ready = None
                raise
            batch: Iterator[T] | None = None
            while True:
                if self._closed or generation != self._generation:
                    return
                if self._detach_error is not None:
                    raise self._detach_error
                if batch is None:
                    await ready.wait()
                    ready.clear()
                    if self._closed or generation != self._generation:
                        return
                    if self._detach_error is not None:
                        raise self._detach_error
                    try:
                        batch = self._do_read()
                    except BlockingIOError:
                        batch = None
                        continue
                try:
                    event = next(batch)
                except StopIteration:
                    batch = None
                    continue
                except BlockingIOError:
                    batch = None
                    continue
                yield event
        finally:
            self._active = False
            if generation == self._generation and self._registered:
                captured_loop = self._loop
                captured_fd = self._fd
                self._generation += 1
                self._registered = False
                self._loop = None
                self._fd = None
                self._ready = None
                if captured_loop is not None and captured_fd is not None:
                    try:
                        closed = captured_loop.is_closed()
                    except Exception as exc:
                        self._note_detach_error(exc)
                    else:
                        if not closed:
                            try:
                                captured_loop.remove_reader(captured_fd)
                            except Exception as exc:
                                self._note_detach_error(exc)
