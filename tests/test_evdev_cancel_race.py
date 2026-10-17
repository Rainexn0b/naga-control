"""Cancel-first race regression through the product adapter."""

import asyncio
import errno
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from contextlib import suppress
from importlib import import_module
from types import SimpleNamespace
from typing import Any

import pytest

from naga_control.adapters.evdev.discovery import EventNode
from naga_control.adapters.evdev.frames import FrameParser, ParsedFrame
from naga_control.adapters.evdev.source import EvdevSource, SourceReadResult
from naga_control.service.source_reader import SourceReader

EBADF_SINGLETON = OSError(errno.EBADF, "fake closed device fd")


class FakeEventIO:
    """Fake fd contract supporting both the old and the owned paths."""

    def __init__(self) -> None:
        self.fd = 424242
        self.log: list[str] = []
        self.closed = False
        self.inners: list[asyncio.Future[Any]] = []
        self.armed: list[Any] = []
        self.info = SimpleNamespace(bustype=3, vendor=0x1532, product=0x00E8, version=0)

    def capabilities(
        self, verbose: bool = False, absinfo: bool = True
    ) -> Mapping[int, Sequence[object]]:
        assert not verbose
        assert absinfo
        return {1: [30]}

    def input_props(self, verbose: bool = False) -> Sequence[int]:
        assert not verbose
        return [0]

    def active_keys(self) -> Collection[int]:
        return []

    def absinfo(self, _axis: int) -> SimpleNamespace:
        return SimpleNamespace(value=0)

    def grab(self) -> None:
        self.log.append("grab")

    def ungrab(self) -> None:
        self.log.append("ungrab")

    def read(self) -> Iterator[Any]:
        if self.closed:
            self.log.append("read-iter-raises-EBADF")
            raise EBADF_SINGLETON
        if not self.armed:
            self.log.append("read-iter-raises-BlockingIO")
            raise BlockingIOError(errno.EAGAIN, "fake no data")
        self.log.append("read-iter-yields-event")
        while self.armed:
            yield self.armed.pop(0)

    def async_read(self) -> asyncio.Future[Any]:
        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self.inners.append(fut)
        self.log.append("async_read-inner-created")
        return fut

    def async_read_loop(self) -> Any:
        upstream: Any = import_module("evdev.eventio_async")
        return upstream.ReadIterator(self)

    def close(self) -> None:
        self.closed = True
        self.log.append("close")


class ClosingSink:
    def __init__(self, source: EvdevSource) -> None:
        self._source = source
        self.frames: list[ParsedFrame] = []
        self.stops = 0

    def start(self) -> None:
        pass

    def consume(self, frame: ParsedFrame) -> None:
        self.frames.append(frame)

    def stop(self) -> None:
        self.stops += 1
        self._source.close()


def _node() -> EventNode:
    return EventNode(
        event_path="fake-event-probe",
        usb_path="fake-usb-ancestor",
        interface_number="01",
        vendor_id="1532",
        product_id="00e8",
    )


def _stack() -> tuple[FakeEventIO, EvdevSource, SourceReader, ClosingSink]:
    fake = FakeEventIO()
    node = _node()
    source = EvdevSource(
        node,
        fake,  # type: ignore[arg-type]
        identity_resolver=lambda _devno: node,
        device_number_resolver=lambda _fd: 7,
    )
    parser = FrameParser(node, {})
    sink = ClosingSink(source)
    reader = SourceReader(source, parser, sink)
    return fake, source, reader, sink


async def _pump(n: int = 15) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


def _handle_append(calls: list[dict[str, Any]]) -> Any:
    def _handle(_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        calls.append(context)

    return _handle


@pytest.mark.asyncio
async def test_cancel_first_queued_lazy_batch_has_no_handler_noise() -> None:
    """Cancel-first then lazy batch must not reach the loop exception handler."""
    loop = asyncio.get_running_loop()
    handler_calls: list[dict[str, Any]] = []
    old_handler = loop.get_exception_handler()
    loop.set_exception_handler(_handle_append(handler_calls))
    readers: dict[int, Callable[[], None]] = {}
    orig_add = loop.add_reader
    orig_remove = loop.remove_reader

    def _fake_add(fd: int, cb: Callable[[], None]) -> None:
        readers[fd] = cb

    def _fake_remove(fd: int) -> bool:
        readers.pop(fd, None)
        return True

    loop.add_reader = _fake_add  # type: ignore[method-assign]
    loop.remove_reader = _fake_remove  # type: ignore[method-assign]
    task: asyncio.Task[SourceReadResult] | None = None
    try:
        fake, _source, reader, _sink = _stack()
        reader.start()
        task = asyncio.create_task(reader.run())
        for _ in range(200):
            if fake.inners or readers:
                break
            await asyncio.sleep(0)
        assert fake.inners or readers
        if fake.inners:
            assert not task.done()
            task.cancel()
            fake.inners[0].set_result(fake.read())
            await _pump(15)
            assert task.cancelled()
        else:
            assert not task.done()
            stale = next(iter(readers.values()))
            task.cancel()
            await _pump(10)
            assert task.cancelled()
            stale()
            await _pump(10)
            assert task.cancelled()
        assert handler_calls == [], f"handler noise: {handler_calls!r}"
    finally:
        loop.add_reader = orig_add  # type: ignore[method-assign]
        loop.remove_reader = orig_remove  # type: ignore[method-assign]
        loop.set_exception_handler(old_handler)
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(task, 2)
        await _pump(5)


@pytest.mark.asyncio
async def test_readiness_first_queued_batch_has_no_handler_noise() -> None:
    """Readiness-first ordering must stay silent on both old and new paths."""
    loop = asyncio.get_running_loop()
    handler_calls: list[dict[str, Any]] = []
    old_handler = loop.get_exception_handler()
    loop.set_exception_handler(_handle_append(handler_calls))
    readers: dict[int, Callable[[], None]] = {}
    orig_add = loop.add_reader
    orig_remove = loop.remove_reader

    def _fake_add(fd: int, cb: Callable[[], None]) -> None:
        readers[fd] = cb

    def _fake_remove(fd: int) -> bool:
        readers.pop(fd, None)
        return True

    loop.add_reader = _fake_add  # type: ignore[method-assign]
    loop.remove_reader = _fake_remove  # type: ignore[method-assign]
    task: asyncio.Task[SourceReadResult] | None = None
    try:
        key = SimpleNamespace(type=1, code=30, value=1)
        syn = SimpleNamespace(type=0, code=0, value=0)
        fake = FakeEventIO()
        fake.armed.extend([key, syn])
        node = _node()
        source = EvdevSource(
            node,
            fake,  # type: ignore[arg-type]
            identity_resolver=lambda _devno: node,
            device_number_resolver=lambda _fd: 7,
        )
        parser = FrameParser(node, {})
        sink = ClosingSink(source)
        reader = SourceReader(source, parser, sink)
        reader.start()
        task = asyncio.create_task(reader.run())
        for _ in range(200):
            if fake.inners or readers:
                break
            await asyncio.sleep(0)
        assert fake.inners or readers
        if fake.inners:
            fake.inners[0].set_result(fake.read())
            await _pump(15)
            assert sink.frames
            assert handler_calls == []
            assert not task.done()
            task.cancel()
            await _pump(10)
            assert task.cancelled()
            assert handler_calls == []
        else:
            assert readers
            cb = next(iter(readers.values()))
            cb()
            await _pump(15)
            assert sink.frames
            assert handler_calls == []
            assert not task.done()
            task.cancel()
            await _pump(10)
            assert task.cancelled()
            assert handler_calls == []
    finally:
        loop.add_reader = orig_add  # type: ignore[method-assign]
        loop.remove_reader = orig_remove  # type: ignore[method-assign]
        loop.set_exception_handler(old_handler)
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(task, 2)
        await _pump(5)
