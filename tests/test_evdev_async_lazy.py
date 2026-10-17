"""Lazy read coverage: immediate vs lazy EAGAIN and genuine lazy errors."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import suppress
from types import SimpleNamespace

import pytest
from evdev_async_reader_fakes import (
    FakeFdDevice,
    LazyFakeDevice,
    anext_event,
    captured_readers,
    make_source,
    pump,
    wait_for,
)

from naga_control.adapters.evdev.frames import EV_KEY, EV_SYN, SYN_REPORT


def _ev(event_type: int, code: int, value: int) -> SimpleNamespace:
    return SimpleNamespace(type=event_type, code=code, value=value)


@pytest.mark.asyncio
@pytest.mark.parametrize("lazy", [False, True])
async def test_eagain_rearms_without_error(lazy: bool) -> None:
    """Immediate vs lazy EAGAIN must both rearm, never EOF or error."""
    empty: tuple[SimpleNamespace, ...] = ()
    if lazy:
        device: FakeFdDevice = LazyFakeDevice(batches=(empty,))
    else:
        device = FakeFdDevice(batches=())
    source = make_source(device)
    with captured_readers() as (readers, _calls):
        it: AsyncGenerator[SimpleNamespace, None] = source.async_read_loop()  # type: ignore[assignment]
        task = asyncio.create_task(anext_event(it))
        try:
            await wait_for(lambda: readers != {})
            cb = next(iter(readers.values()))
            cb()
            await wait_for(lambda: device.read_calls >= 1)
            await pump(10)
            assert not task.done(), "EAGAIN must stay parked, not EOF or error"
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


@pytest.mark.asyncio
async def test_lazy_eagain_then_valid_batch_delivers() -> None:
    """Mixed sequence: lazy EAGAIN first stays parked, later valid batch reads."""
    valid: tuple[SimpleNamespace, ...] = (_ev(1, 30, 1), _ev(0, 0, 0))
    empty: tuple[SimpleNamespace, ...] = ()
    device: FakeFdDevice = LazyFakeDevice(batches=(empty, valid))
    source = make_source(device)
    with captured_readers() as (readers, _calls):
        it: AsyncGenerator[SimpleNamespace, None] = source.async_read_loop()  # type: ignore[assignment]
        task = asyncio.create_task(anext_event(it))
        try:
            await wait_for(lambda: readers != {})
            cb = next(iter(readers.values()))
            cb()
            await wait_for(lambda: device.read_calls >= 1)  # pyright: ignore[reportUnknownMemberType]
            await pump(10)
            assert not task.done(), "first lazy EAGAIN must not end stream"
            cb2 = next(iter(readers.values()))
            cb2()
            event = await asyncio.wait_for(task, 2)
            assert (event.type, event.code, event.value) == (1, 30, 1)
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(task, 2)
            await it.aclose()
            with suppress(Exception):
                source.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_errno", [9, 5, 19, 1])
async def test_lazy_genuine_errors_preserve_identity(failing_errno: int) -> None:
    """Lazy OSError from next() must propagate exact object, not rearm."""
    primary = OSError(failing_errno, "lazy genuine failure")
    device = LazyFakeDevice(read_error=primary)
    source = make_source(device)
    with captured_readers() as (readers, _calls):
        it: AsyncGenerator[SimpleNamespace, None] = source.async_read_loop()  # type: ignore[assignment]
        task = asyncio.create_task(anext_event(it))
        try:
            await wait_for(lambda: readers != {})
            cb = next(iter(readers.values()))
            cb()
            with pytest.raises(OSError) as caught:
                await asyncio.wait_for(task, 2)
            assert caught.value is primary
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(task, 2)
            await it.aclose()
            with suppress(Exception):
                source.close()


@pytest.mark.asyncio
async def test_lazy_spurious_then_valid_through_real_selector() -> None:
    """Spurious lazy EAGAIN on a real pipe stays parked, then valid reads."""
    from evdev_async_reader_fakes import PipeDevice

    valid = (_ev(EV_KEY, 30, 1), _ev(EV_SYN, SYN_REPORT, 0))
    device = PipeDevice(batches=(valid,))
    source = make_source(device)
    loop = asyncio.get_running_loop()
    task: asyncio.Task[SimpleNamespace] | None = None
    try:
        it: AsyncGenerator[SimpleNamespace, None] = source.async_read_loop()  # type: ignore[assignment]
        task = asyncio.create_task(anext_event(it))
        await asyncio.sleep(0.05)
        device.signal_readable()
        event = await asyncio.wait_for(task, 2)
        assert (event.type, event.code) == (EV_KEY, 30)
        await it.aclose()
    finally:
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(task, 2)
        with suppress(Exception):
            source.close()
        device.drain_signal()
        device.close_sockets()
        _ = loop
