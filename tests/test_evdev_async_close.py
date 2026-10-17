"""Owned close lifecycle: rollback, failure identity, and real selector."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import suppress
from types import SimpleNamespace
from typing import Any

import pytest
from evdev_async_reader_fakes import (
    FakeFdDevice,
    PipeDevice,
    anext_event,
    captured_readers,
    make_node,
    make_source,
    pump,
    wait_for,
)

from naga_control.adapters.evdev.frames import (
    EV_KEY,
    EV_SYN,
    SYN_REPORT,
    FrameParser,
    RawControlSignature,
)
from naga_control.service.source_reader import SourceReader


def _ev(event_type: int, code: int, value: int) -> SimpleNamespace:
    return SimpleNamespace(type=event_type, code=code, value=value)


def _parser() -> FrameParser:
    node = make_node("01")
    sig = RawControlSignature("00e8", "01", EV_KEY, 30, None)
    return FrameParser(node, {sig: "ring_finger"})


def _handle_append(calls: list[dict[str, Any]]) -> Any:
    def _handle(_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        calls.append(context)

    return _handle


@pytest.mark.asyncio
async def test_never_entered_reader_start_rollback_is_clean() -> None:
    device = FakeFdDevice(batches=())
    source = make_source(device)
    with captured_readers() as (readers, _calls):

        class Sink:
            def start(self) -> None:
                raise RuntimeError("sink start failed")

            def consume(self, frame: object) -> None:
                raise AssertionError("must not consume")

            def stop(self) -> None:
                source.close()

        reader = SourceReader(source, _parser(), Sink())  # type: ignore[arg-type]
        with pytest.raises(RuntimeError, match="sink start failed"):
            reader.start()
        reader.stop()
        assert readers == {}
        assert device.close_calls == 1


@pytest.mark.asyncio
async def test_close_failure_preserves_first_error_identity() -> None:
    close_error = OSError(5, "genuine close failed")
    device = FakeFdDevice(close_errors=(close_error,))
    source = make_source(device)
    with captured_readers():
        with pytest.raises(OSError) as caught:
            source.close()
        assert caught.value is close_error
        assert device.close_calls == 1
        source.close()
        assert device.close_calls == 2


@pytest.mark.asyncio
async def test_pipe_delivery_through_real_selector() -> None:
    batch = (_ev(EV_KEY, 30, 1), _ev(EV_SYN, SYN_REPORT, 0))
    device = PipeDevice(batches=(batch,))
    source = make_source(device)
    loop = asyncio.get_running_loop()
    handler_calls: list[dict[str, Any]] = []
    old_handler = loop.get_exception_handler()
    loop.set_exception_handler(_handle_append(handler_calls))
    task: asyncio.Task[SimpleNamespace] | None = None
    try:
        it: AsyncGenerator[SimpleNamespace, None] = source.async_read_loop()  # type: ignore[assignment]
        task = asyncio.create_task(anext_event(it))
        await asyncio.sleep(0.05)
        device.signal_readable()
        event = await asyncio.wait_for(task, 2)
        assert (event.type, event.code, event.value) == (EV_KEY, 30, 1)
        assert handler_calls == []
        await it.aclose()
    finally:
        loop.set_exception_handler(old_handler)
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(task, 2)
        with suppress(Exception):
            source.close()
        device.drain_signal()
        device.close_sockets()


@pytest.mark.asyncio
async def test_reader_cancel_gives_clean_owned_stop() -> None:
    device = FakeFdDevice(batches=())
    source = make_source(device)
    loop = asyncio.get_running_loop()
    handler_calls: list[dict[str, Any]] = []
    old_handler = loop.get_exception_handler()
    loop.set_exception_handler(_handle_append(handler_calls))
    with captured_readers() as (readers, _calls):
        frames: list[object] = []

        class Sink:
            def __init__(self) -> None:
                self.stops = 0

            def start(self) -> None:
                pass

            def consume(self, frame: object) -> None:
                frames.append(frame)

            def stop(self) -> None:
                self.stops += 1
                source.close()

        reader = SourceReader(source, _parser(), Sink())  # type: ignore[arg-type]
        reader.start()
        task = asyncio.create_task(reader.run())
        try:
            await wait_for(lambda: readers != {})
            task.cancel()
            await pump(10)
            assert task.cancelled()
            assert handler_calls == []
            assert readers == {}
        finally:
            loop.set_exception_handler(old_handler)
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(task, 2)
            with suppress(Exception):
                reader.stop()
            with suppress(Exception):
                source.close()


@pytest.mark.asyncio
async def test_remove_failure_with_clean_close_caches_and_blocks_retry() -> None:
    """Remove failure + clean device close: both attempted, first wins, no retry."""
    from evdev_async_reader_fakes import failing_remove_readers

    remove_error = OSError(5, "genuine remove failed")
    device = FakeFdDevice(batches=())
    source = make_source(device)
    with failing_remove_readers(remove_error) as (readers, calls):
        it = source.async_read_loop()
        task = asyncio.create_task(anext_event(it))  # type: ignore[arg-type]
        try:
            await wait_for(lambda: readers != {})
            task.cancel()
            with suppress(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
            await it.aclose()
            # Finally cached the remove failure; close must surface it.
            with pytest.raises(OSError) as caught:
                source.close()
            assert caught.value is remove_error
            assert device.close_calls == 1
            removes_before = calls.count(f"remove:{device.fd}")
            closes_before = device.close_calls
            with pytest.raises(OSError) as cached:
                source.close()
            assert cached.value is remove_error
            assert calls.count(f"remove:{device.fd}") == removes_before
            assert device.close_calls == closes_before
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(task, 2)
            await it.aclose()


@pytest.mark.asyncio
async def test_remove_and_device_close_both_fail_first_wins() -> None:
    """Both detach and device close fail: both attempted, detach identity wins."""
    from evdev_async_reader_fakes import failing_remove_readers

    remove_error = OSError(5, "remove failed")
    close_error = OSError(5, "close failed")
    device = FakeFdDevice(batches=(), close_errors=(close_error,))
    source = make_source(device)
    with failing_remove_readers(remove_error) as (readers, _calls):
        it = source.async_read_loop()
        task = asyncio.create_task(anext_event(it))  # type: ignore[arg-type]
        try:
            await wait_for(lambda: readers != {})
            task.cancel()
            with suppress(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
            await it.aclose()
            with pytest.raises(OSError) as caught:
                source.close()
            assert caught.value is remove_error
            assert caught.value.__cause__ is close_error
            assert device.close_calls == 1
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(task, 2)
            await it.aclose()


@pytest.mark.asyncio
async def test_is_closed_failure_is_not_clean() -> None:
    """loop.is_closed raising must surface as detach error, not clean no-op."""
    is_closed_error = OSError(5, "is_closed failed")
    device = FakeFdDevice(batches=())
    source = make_source(device)
    with captured_readers() as (readers, _calls):
        it = source.async_read_loop()  # type: ignore[assignment]
        task = asyncio.create_task(anext_event(it))  # type: ignore[arg-type]
        loop = asyncio.get_running_loop()
        orig_is_closed = loop.is_closed
        try:
            await wait_for(lambda: readers != {})

            def _fail() -> bool:
                raise is_closed_error

            loop.is_closed = _fail  # type: ignore[method-assign]
            with pytest.raises(OSError) as caught:
                source.close()
            assert caught.value is is_closed_error
            assert device.close_calls == 1
        finally:
            loop.is_closed = orig_is_closed  # type: ignore[method-assign]
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(task, 2)
            await it.aclose()


@pytest.mark.asyncio
async def test_detach_failure_keeps_lifecycle_unsafe() -> None:
    """Genuine detach failure through a real session stays unsafe."""
    from naga_control.service.session_lifecycle import SessionLifecycle

    remove_error = OSError(5, "detach failed")
    events: list[str] = []

    class FailingSession:
        async def start(self) -> None:
            events.append("start")

        async def stop(self) -> None:
            events.append("stop")
            raise remove_error

        def release_all(self) -> None:
            events.append("release")

    lifecycle = SessionLifecycle(lambda: events.append("fence"))
    await lifecycle.start(FailingSession())  # type: ignore[arg-type]
    with pytest.raises(OSError) as caught:
        await lifecycle.stop()
    assert caught.value is remove_error
    assert lifecycle.unsafe
    assert lifecycle.current is None
