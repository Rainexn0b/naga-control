"""Owned readiness batch iterator: delivery, errors, cancel, and fd reuse."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import suppress
from types import SimpleNamespace
from typing import Any

import pytest
from evdev_async_reader_fakes import (
    FakeFdDevice,
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
    LogicalControlEvent,
    ParsedFrame,
    RawControlSignature,
    RawInputEvent,
)
from naga_control.adapters.evdev.source import SourceReadResult, read_parsed_frames


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
async def test_batch_delivery_preserves_type_order() -> None:
    device = FakeFdDevice(
        batches=(
            (_ev(EV_KEY, 30, 1), _ev(EV_SYN, SYN_REPORT, 0)),
            (_ev(EV_KEY, 30, 0), _ev(EV_SYN, SYN_REPORT, 0)),
        )
    )
    source = make_source(device)
    frames: list[ParsedFrame] = []

    async def _collect() -> SourceReadResult:
        return await read_parsed_frames(source, _parser(), frames.append)

    with captured_readers() as (readers, _calls):
        task = asyncio.create_task(_collect())
        try:
            await wait_for(lambda: readers != {})
            assert len(readers) == 1
            cb = next(iter(readers.values()))
            cb()
            await wait_for(lambda: device.read_calls >= 1)
            await pump(5)
            cb2 = next(iter(readers.values()))
            cb2()
            await wait_for(lambda: len(frames) >= 2)
            source.close()
            result = await asyncio.wait_for(task, 2)
            assert result.error is None
            assert len(frames) == 2, f"expected exactly press+release, got {frames!r}"
            first, second = frames
            assert first.events == (
                RawInputEvent(EV_KEY, 30, 1),
                RawInputEvent(EV_SYN, SYN_REPORT, 0),
            )
            assert first.controls == (LogicalControlEvent("ring_finger", 1, 0, None),)
            assert first.reset_controls == ()
            assert not first.resync_required
            assert second.events == (
                RawInputEvent(EV_KEY, 30, 0),
                RawInputEvent(EV_SYN, SYN_REPORT, 0),
            )
            assert second.controls == (LogicalControlEvent("ring_finger", 0, 0, None),)
            assert second.reset_controls == ()
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(task, 2)
            with suppress(Exception):
                source.close()


@pytest.mark.asyncio
async def test_spurious_ready_rearms_without_busy_loop() -> None:
    device = FakeFdDevice(batches=())
    source = make_source(device)
    it: AsyncGenerator[SimpleNamespace, None] = source.async_read_loop()  # type: ignore[assignment]
    with captured_readers() as (readers, _calls):
        task = asyncio.create_task(anext_event(it))
        try:
            await wait_for(lambda: readers != {})
            cb = next(iter(readers.values()))
            cb()
            await wait_for(lambda: device.read_calls >= 1)
            await pump(10)
            assert device.read_calls == 1
            assert len(readers) == 1
            task.cancel()
            with suppress(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(task, 2)
            await it.aclose()
            with suppress(Exception):
                source.close()
            await pump(3)


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_errno", [9, 5, 19, 1])
async def test_genuine_read_errors_propagate_exact_object(failing_errno: int) -> None:
    primary = OSError(failing_errno, "genuine read failure")
    device = FakeFdDevice(read_error=primary)
    source = make_source(device)
    frames: list[ParsedFrame] = []
    with captured_readers() as (readers, _calls):
        task = asyncio.create_task(read_parsed_frames(source, _parser(), frames.append))
        try:
            await wait_for(lambda: readers != {})
            cb = next(iter(readers.values()))
            cb()
            result = await asyncio.wait_for(task, 2)
            assert result.error is primary
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(task, 2)
            with suppress(Exception):
                source.close()


@pytest.mark.asyncio
async def test_cancel_while_waiting_leaves_no_reader_task_future() -> None:
    device = FakeFdDevice(batches=())
    source = make_source(device)
    loop = asyncio.get_running_loop()
    handler_calls: list[dict[str, Any]] = []
    old_handler = loop.get_exception_handler()
    loop.set_exception_handler(_handle_append(handler_calls))
    with captured_readers() as (readers, _calls):
        it: AsyncGenerator[SimpleNamespace, None] = source.async_read_loop()  # type: ignore[assignment]
        task = asyncio.create_task(anext_event(it))
        try:
            await wait_for(lambda: readers != {})
            assert len(readers) == 1
            task.cancel()
            with suppress(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
            await it.aclose()
            await pump(5)
            assert readers == {}
            guard = source._readiness  # pyright: ignore[reportPrivateUsage]
            assert guard._loop is None  # pyright: ignore[reportPrivateUsage]
            assert guard._fd is None  # pyright: ignore[reportPrivateUsage]
            assert guard._ready is None  # pyright: ignore[reportPrivateUsage]
            assert not guard._registered  # pyright: ignore[reportPrivateUsage]
            assert len(asyncio.all_tasks()) == 1
            assert handler_calls == []
        finally:
            loop.set_exception_handler(old_handler)
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(task, 2)
            await it.aclose()
            with suppress(Exception):
                source.close()


@pytest.mark.asyncio
async def test_close_wakes_waiter_without_manufactured_ebadf() -> None:
    device = FakeFdDevice(batches=())
    source = make_source(device)
    with captured_readers() as (readers, _calls):
        it: AsyncGenerator[SimpleNamespace, None] = source.async_read_loop()  # type: ignore[assignment]
        task = asyncio.create_task(anext_event(it))
        try:
            await wait_for(lambda: readers != {})
            reads_before = device.read_calls
            source.close()
            with pytest.raises(StopAsyncIteration):
                await asyncio.wait_for(task, 2)
            assert device.read_calls == reads_before
            assert readers == {}
            assert device.close_calls == 1
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(task, 2)
            await it.aclose()
            with suppress(Exception):
                source.close()


@pytest.mark.asyncio
async def test_close_twice_and_close_before_enter() -> None:
    device = FakeFdDevice(batches=())
    source = make_source(device)
    with captured_readers() as (readers, calls):
        source.close()
        source.close()
        assert device.close_calls == 1
        assert readers == {}
        assert calls == []
        it: AsyncGenerator[SimpleNamespace, None] = source.async_read_loop()  # type: ignore[assignment]
        task = asyncio.create_task(anext_event(it))
        try:
            with pytest.raises(StopAsyncIteration):
                await asyncio.wait_for(task, 2)
            assert readers == {}
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(task, 2)
            await it.aclose()


@pytest.mark.asyncio
async def test_fd_reuse_old_callback_is_benign() -> None:
    shared_fd = 5555
    old_device = FakeFdDevice(
        fd=shared_fd,
        batches=((_ev(EV_KEY, 30, 1), _ev(EV_SYN, SYN_REPORT, 0)),),
    )
    old_source = make_source(old_device)
    with captured_readers() as (readers, calls):
        old_it: AsyncGenerator[SimpleNamespace, None] = old_source.async_read_loop()  # type: ignore[assignment]
        old_task = asyncio.create_task(anext_event(old_it))
        new_it: AsyncGenerator[SimpleNamespace, None] | None = None
        new_task: asyncio.Task[SimpleNamespace] | None = None
        new_source = None
        try:
            await wait_for(lambda: readers != {})
            old_cb = next(iter(readers.values()))
            old_cb()
            event = await asyncio.wait_for(old_task, 2)
            assert (event.type, event.code) == (EV_KEY, 30)
            old_reads = old_device.read_calls
            old_source.close()
            assert readers == {}
            new_device = FakeFdDevice(
                fd=shared_fd,
                batches=((_ev(EV_KEY, 30, 1), _ev(EV_SYN, SYN_REPORT, 0)),),
            )
            new_source = make_source(new_device)
            new_it = new_source.async_read_loop()  # type: ignore[assignment]
            assert new_it is not None
            new_task = asyncio.create_task(anext_event(new_it))
            assert new_task is not None
            await wait_for(lambda: readers != {})
            assert len(readers) == 1
            new_cb = next(iter(readers.values()))
            assert new_cb is not old_cb
            await old_it.aclose()
            assert len(readers) == 1
            assert next(iter(readers.values())) is new_cb
            old_cb()
            await pump(5)
            assert new_device.read_calls == 0
            assert old_device.read_calls == old_reads
            assert len(readers) == 1
            new_cb()
            fresh = await asyncio.wait_for(new_task, 2)
            assert (fresh.type, fresh.code) == (EV_KEY, 30)
            await new_it.aclose()
        finally:
            if new_task is not None and not new_task.done():
                new_task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(new_task, 2)
            if new_it is not None:
                await new_it.aclose()
            if new_source is not None:
                with suppress(Exception):
                    new_source.close()
            if not old_task.done():
                old_task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(old_task, 2)
            await old_it.aclose()
            with suppress(Exception):
                old_source.close()
        assert calls.count(f"add:{shared_fd}") == 2
        assert calls.count(f"remove:{shared_fd}") == 2


@pytest.mark.asyncio
async def test_concurrent_readers_reject_without_stealing() -> None:
    device = FakeFdDevice(batches=((_ev(EV_KEY, 30, 1),),))
    source = make_source(device)
    with captured_readers() as (readers, _calls):
        first: AsyncGenerator[SimpleNamespace, None] = source.async_read_loop()  # type: ignore[assignment]
        first_task = asyncio.create_task(anext_event(first))
        try:
            await wait_for(lambda: readers != {})
            assert len(readers) == 1
            first_cb = next(iter(readers.values()))
            second: AsyncGenerator[SimpleNamespace, None] = source.async_read_loop()  # type: ignore[assignment]
            with pytest.raises(RuntimeError, match="already active"):
                await anext_event(second)
            assert len(readers) == 1
            assert next(iter(readers.values())) is first_cb
            first_task.cancel()
            with suppress(asyncio.CancelledError):
                await asyncio.wait_for(first_task, 2)
        finally:
            if not first_task.done():
                first_task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(first_task, 2)
            await first.aclose()
            with suppress(Exception):
                source.close()
