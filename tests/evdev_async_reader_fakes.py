"""Shared fakes for owned evdev readiness tests."""

import asyncio
import errno
import socket
from collections.abc import AsyncGenerator, Callable, Generator, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from types import SimpleNamespace

from naga_control.adapters.evdev.discovery import EventNode
from naga_control.adapters.evdev.source import EvdevSource


class FakeInfo:
    bustype = 3
    vendor = 0x1532
    product = 0x00E8
    version = 1


_fd_counter = 1000


def _next_fake_fd() -> int:
    global _fd_counter
    _fd_counter += 1
    return _fd_counter


class FakeFdDevice:
    """Fake descriptor with a non-real fd for controlled-callback tests."""

    info = FakeInfo()

    def __init__(
        self,
        *,
        fd: int | None = None,
        batches: tuple[tuple[SimpleNamespace, ...], ...] = (),
        read_error: BaseException | None = None,
        close_errors: tuple[Exception, ...] = (),
    ) -> None:
        self.fd = fd if fd is not None else _next_fake_fd()
        self._batches = [list(batch) for batch in batches]
        self._read_error = read_error
        self._close_errors = list(close_errors)
        self.read_calls = 0
        self.close_calls = 0
        self.closed = False
        self.grab_calls = 0
        self.ungrab_calls = 0

    def grab(self) -> None:
        self.grab_calls += 1

    def ungrab(self) -> None:
        self.ungrab_calls += 1

    def close(self) -> None:
        self.close_calls += 1
        if self._close_errors:
            raise self._close_errors.pop(0)
        self.closed = True

    def input_props(self, verbose: bool = False) -> Sequence[int]:
        assert not verbose
        return (0,)

    def capabilities(
        self, verbose: bool = False, absinfo: bool = True
    ) -> Mapping[int, Sequence[object]]:
        assert not verbose
        assert absinfo
        return {1: (30,)}

    def active_keys(self) -> tuple[int, ...]:
        return ()

    def absinfo(self, _axis: int) -> SimpleNamespace:
        return SimpleNamespace(value=0)

    def read(self) -> Iterator[SimpleNamespace]:
        self.read_calls += 1
        if self.closed:
            raise OSError(errno.EBADF, "fake closed descriptor")
        if self._read_error is not None:
            raise self._read_error
        if not self._batches:
            raise BlockingIOError(errno.EAGAIN, "no data")
        batch = self._batches.pop(0)
        return iter(batch)


class LazyFakeDevice(FakeFdDevice):
    """Realistic lazy read: EAGAIN and errors surface on next(), not on call."""

    def read(self) -> Iterator[SimpleNamespace]:
        self.read_calls += 1

        def _gen() -> Iterator[SimpleNamespace]:
            if self.closed:
                raise OSError(errno.EBADF, "fake closed descriptor")
            if self._read_error is not None:
                raise self._read_error
            if not self._batches:
                raise BlockingIOError(errno.EAGAIN, "no data")
            batch = self._batches.pop(0)
            if len(batch) == 0:
                raise BlockingIOError(errno.EAGAIN, "spurious readiness")
            yield from batch

        return _gen()


class PipeDevice(FakeFdDevice):
    """Fake device whose fd is a real socketpair read end for selector tests."""

    def __init__(
        self,
        *,
        batches: tuple[tuple[SimpleNamespace, ...], ...] = (),
        read_error: BaseException | None = None,
    ) -> None:
        self._rsock, self._wsock = socket.socketpair()
        self._rsock.setblocking(False)
        self._wsock.setblocking(False)
        super().__init__(fd=self._rsock.fileno(), batches=batches, read_error=read_error)

    def signal_readable(self) -> None:
        with suppress(BlockingIOError):
            self._wsock.send(b"x")

    def drain_signal(self) -> None:
        with suppress(BlockingIOError):
            while self._rsock.recv(1024):
                pass

    def close_sockets(self) -> None:
        for sock in (self._rsock, self._wsock):
            with suppress(OSError):
                sock.close()


def make_node(interface: str = "01") -> EventNode:
    return EventNode(
        event_path=f"/dev/input/fake-{interface}",
        usb_path="/sys/devices/fake-physical-usb",
        interface_number=interface,
        vendor_id="1532",
        product_id="00e8",
    )


def make_source(device: FakeFdDevice, node: EventNode | None = None) -> EvdevSource:
    actual = node if node is not None else make_node()
    return EvdevSource(
        actual,
        device,  # type: ignore[arg-type]
        identity_resolver=lambda _devno: actual,
        device_number_resolver=lambda _fd: 7,
    )


async def pump(n: int = 10) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


async def wait_for(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    async def _poll() -> None:
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(_poll(), timeout)


@contextmanager
def captured_readers() -> Generator[tuple[dict[int, Callable[[], None]], list[str]], None, None]:
    """Capture loop.add_reader callbacks without touching real selectors."""
    loop = asyncio.get_running_loop()
    readers: dict[int, Callable[[], None]] = {}
    calls: list[str] = []
    orig_add = loop.add_reader
    orig_remove = loop.remove_reader

    def _add(fd: int, cb: Callable[[], None]) -> None:
        calls.append(f"add:{fd}")
        readers[fd] = cb

    def _remove(fd: int) -> bool:
        calls.append(f"remove:{fd}")
        readers.pop(fd, None)
        return True

    loop.add_reader = _add  # type: ignore[method-assign]
    loop.remove_reader = _remove  # type: ignore[method-assign]
    try:
        yield readers, calls
    finally:
        loop.add_reader = orig_add  # type: ignore[method-assign]
        loop.remove_reader = orig_remove  # type: ignore[method-assign]


@contextmanager
def failing_remove_readers(
    remove_error: Exception,
) -> Generator[tuple[dict[int, Callable[[], None]], list[str]], None, None]:
    """Capture readers but make remove_reader raise once with exact identity."""
    loop = asyncio.get_running_loop()
    readers: dict[int, Callable[[], None]] = {}
    calls: list[str] = []
    orig_add = loop.add_reader
    orig_remove = loop.remove_reader
    state: dict[str, int] = {"removes": 0}

    def _add(fd: int, cb: Callable[[], None]) -> None:
        calls.append(f"add:{fd}")
        readers[fd] = cb

    def _remove(fd: int) -> bool:
        calls.append(f"remove:{fd}")
        state["removes"] += 1
        readers.pop(fd, None)
        if state["removes"] == 1:
            raise remove_error
        return True

    loop.add_reader = _add  # type: ignore[method-assign]
    loop.remove_reader = _remove  # type: ignore[method-assign]
    try:
        yield readers, calls
    finally:
        loop.add_reader = orig_add  # type: ignore[method-assign]
        loop.remove_reader = orig_remove  # type: ignore[method-assign]


@contextmanager
def is_closed_failing_readers(
    is_closed_error: Exception,
) -> Generator[tuple[dict[int, Callable[[], None]], list[str]], None, None]:
    """Capture readers but make loop.is_closed raise with exact identity."""
    loop = asyncio.get_running_loop()
    readers: dict[int, Callable[[], None]] = {}
    calls: list[str] = []
    orig_add = loop.add_reader
    orig_remove = loop.remove_reader
    orig_is_closed = loop.is_closed

    def _add(fd: int, cb: Callable[[], None]) -> None:
        calls.append(f"add:{fd}")
        readers[fd] = cb

    def _remove(fd: int) -> bool:
        calls.append(f"remove:{fd}")
        readers.pop(fd, None)
        return True

    def _is_closed() -> bool:
        raise is_closed_error

    loop.add_reader = _add  # type: ignore[method-assign]
    loop.remove_reader = _remove  # type: ignore[method-assign]
    loop.is_closed = _is_closed  # type: ignore[method-assign]
    try:
        yield readers, calls
    finally:
        loop.add_reader = orig_add  # type: ignore[method-assign]
        loop.remove_reader = orig_remove  # type: ignore[method-assign]
        loop.is_closed = orig_is_closed  # type: ignore[method-assign]


async def anext_event(it: AsyncGenerator[SimpleNamespace, None]) -> SimpleNamespace:
    return await it.__anext__()
