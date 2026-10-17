"""Session reader-failure fail-open: strict health replaces phantom healthy."""

import asyncio
import logging
from collections.abc import Callable

import pytest
from reader_failure_fakes import FakeActions, FakeKeyboard, FakeMouse, make_connection

from naga_control.adapters.evdev.discovery import EventNode
from naga_control.adapters.evdev.source import SourceReadResult
from naga_control.application.remapping import FirstSliceSession, PreparedSource
from naga_control.domain.defaults import default_configuration
from naga_control.ports.forwarding import ForwardingProxy, ForwardingProxySpec


class FakeReader:
    def __init__(self, node: EventNode, mode: str, error: BaseException | None = None) -> None:
        self.node = node
        self.mode = mode
        self.error = error
        self.started = False
        self.stopped = False
        self.stop_calls = 0

    def start(self) -> None:
        self.started = True

    async def run(self) -> object:
        if self.mode == "hang":
            await asyncio.Event().wait()
            return SourceReadResult(None)
        if self.mode == "raise":
            assert self.error is not None
            raise self.error
        if self.mode == "result_error":
            return SourceReadResult(self.error)  # type: ignore[arg-type]
        return SourceReadResult(None)

    def stop(self) -> None:
        self.stop_calls += 1
        self.stopped = True


def _make_session(
    readers: dict[str, FakeReader],
    failures: list[FirstSliceSession],
    keyboard: FakeKeyboard,
    mouse: FakeMouse,
    events: list[str],
) -> FirstSliceSession:
    connection = make_connection()
    profile = default_configuration().profile("default")

    def opener(node: EventNode) -> PreparedSource:
        from reader_failure_fakes import HangingSource

        return HangingSource(node)  # type: ignore[return-value]

    def factory(
        source: PreparedSource,
        profile_arg: object,
        keyboard_arg: object,
        mouse_arg: object,
        device_actions: object,
        proxy_factory: object,
        readiness_waiter: object,
    ) -> FakeReader:
        return readers[source.node.interface_number]

    return FirstSliceSession(
        connection,
        profile,
        keyboard,  # type: ignore[arg-type]
        mouse,  # type: ignore[arg-type]
        FakeActions(events),  # type: ignore[arg-type]
        opener,
        _ProxyFactory(),
        _Waiter(),
        factory,  # type: ignore[arg-type]
        on_failure=failures.append,
    )


class _ProxyFactory:
    def create(self, spec: ForwardingProxySpec) -> ForwardingProxy:
        raise AssertionError("session failure tests use fake readers")


class _Waiter:
    def wait_ready(self, spec: ForwardingProxySpec) -> None:
        raise AssertionError("session failure tests use fake readers")


async def _wait_for(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    await asyncio.wait_for(_poll(predicate), timeout)


async def _poll(predicate: Callable[[], bool]) -> None:
    while not predicate():
        await asyncio.sleep(0.01)


@pytest.mark.parametrize("mode", ["raise", "result_error", "eof"])
async def test_unexpected_reader_end_is_exactly_once_failure(mode: str) -> None:
    keyboard = FakeKeyboard()
    mouse = FakeMouse()
    events: list[str] = []
    failures: list[FirstSliceSession] = []
    error = OSError(19, "no such device")
    readers = {
        "00": FakeReader(make_connection().nodes[0], "hang"),
        "01": FakeReader(make_connection().nodes[1], mode, error if mode != "eof" else None),
        "02": FakeReader(make_connection().nodes[2], "hang"),
    }
    session = _make_session(readers, failures, keyboard, mouse, events)
    try:
        await session.start()
        assert session.running
        await _wait_for(lambda: keyboard.released)
        assert keyboard.released and mouse.released
        assert not session.running
        assert failures == [session]
        if mode == "eof":
            assert session.errors == ()
        else:
            assert len(session.errors) == 1
    finally:
        await asyncio.wait_for(session.stop(), 2)
    assert all(r.stopped for r in readers.values())
    assert all(r.stop_calls == 1 for r in readers.values())


async def test_unexpected_cancel_is_exactly_once_failure() -> None:
    keyboard = FakeKeyboard()
    mouse = FakeMouse()
    events: list[str] = []
    failures: list[FirstSliceSession] = []
    readers = {
        interface: FakeReader(make_connection().nodes[i], "hang")
        for i, interface in enumerate(("00", "01", "02"))
    }
    session = _make_session(readers, failures, keyboard, mouse, events)
    try:
        await session.start()
        assert session.running
        task = session._tasks[0]  # pyright: ignore[reportPrivateUsage]
        task.cancel()
        await _wait_for(lambda: keyboard.released)
        assert not session.running
        assert failures == [session]
    finally:
        await asyncio.wait_for(session.stop(), 2)


async def test_old_api_without_callback_has_strict_health() -> None:
    keyboard = FakeKeyboard()
    mouse = FakeMouse()
    events: list[str] = []
    connection = make_connection()
    profile = default_configuration().profile("default")

    def opener(node: EventNode) -> PreparedSource:
        from reader_failure_fakes import HangingSource

        return HangingSource(node)  # type: ignore[return-value]

    readers = {
        "00": FakeReader(connection.nodes[0], "hang"),
        "01": FakeReader(connection.nodes[1], "result_error", OSError(19, "gone")),
        "02": FakeReader(connection.nodes[2], "hang"),
    }

    def factory(
        source: PreparedSource,
        _p: object,
        _k: object,
        _m: object,
        _d: object,
        _f: object,
        _w: object,
    ) -> FakeReader:
        return readers[source.node.interface_number]

    session = FirstSliceSession(
        connection,
        profile,
        keyboard,  # type: ignore[arg-type]
        mouse,  # type: ignore[arg-type]
        FakeActions(events),  # type: ignore[arg-type]
        opener,
        _ProxyFactory(),
        _Waiter(),
        factory,  # type: ignore[arg-type]
    )
    try:
        await session.start()
        await _wait_for(lambda: len(session.errors) == 1)
        assert not session.running, "strict health must fail when one reader ends"
        assert keyboard.released
    finally:
        await asyncio.wait_for(session.stop(), 2)


async def test_intentional_stop_has_no_callback_no_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    keyboard = FakeKeyboard()
    mouse = FakeMouse()
    events: list[str] = []
    failures: list[FirstSliceSession] = []
    readers = {
        interface: FakeReader(make_connection().nodes[i], "hang")
        for i, interface in enumerate(("00", "01", "02"))
    }
    session = _make_session(readers, failures, keyboard, mouse, events)
    with caplog.at_level(logging.WARNING):
        await session.start()
        assert session.running
        stop_task = session._stop_task  # pyright: ignore[reportPrivateUsage]
        assert stop_task is None
        await asyncio.wait_for(session.stop(), 2)
        assert session._stop_task is not None  # pyright: ignore[reportPrivateUsage]
    assert failures == []
    assert session.errors == ()
    assert not any("stopped unexpectedly" in r.getMessage() for r in caplog.records)


async def test_startup_rollback_has_no_callback() -> None:
    keyboard = FakeKeyboard()
    mouse = FakeMouse()
    events: list[str] = []
    failures: list[FirstSliceSession] = []
    connection = make_connection()
    profile = default_configuration().profile("default")

    def opener(node: EventNode) -> PreparedSource:
        from reader_failure_fakes import HangingSource

        return HangingSource(node)  # type: ignore[return-value]

    def factory(
        source: PreparedSource,
        _p: object,
        _k: object,
        _m: object,
        _d: object,
        _f: object,
        _w: object,
    ) -> FakeReader:
        if source.node.interface_number == "01":
            raise RuntimeError("physical source is already grabbed")
        return FakeReader(source.node, "hang")

    session = FirstSliceSession(
        connection,
        profile,
        keyboard,  # type: ignore[arg-type]
        mouse,  # type: ignore[arg-type]
        FakeActions(events),  # type: ignore[arg-type]
        opener,
        _ProxyFactory(),
        _Waiter(),
        factory,  # type: ignore[arg-type]
        on_failure=failures.append,
    )
    with pytest.raises(RuntimeError, match="already grabbed"):
        await session.start()
    assert failures == []
    assert session.errors == ()
    assert not session.running


async def test_late_failures_after_stop_are_ignored(
    caplog: pytest.LogCaptureFixture,
) -> None:
    keyboard = FakeKeyboard()
    mouse = FakeMouse()
    events: list[str] = []
    failures: list[FirstSliceSession] = []
    readers = {
        interface: FakeReader(make_connection().nodes[i], "hang")
        for i, interface in enumerate(("00", "01", "02"))
    }
    session = _make_session(readers, failures, keyboard, mouse, events)
    try:
        await session.start()
        saved_tasks = list(session._tasks)  # pyright: ignore[reportPrivateUsage]
        assert len(saved_tasks) == 3
        saved_tasks[0].cancel()
        await _wait_for(lambda: keyboard.released)
        assert failures == [session]
        saved_errors = tuple(session.errors)
        with caplog.at_level(logging.WARNING):
            caplog.clear()
            await asyncio.wait_for(session.stop(), 2)
            assert session._tasks == []  # pyright: ignore[reportPrivateUsage]
            for task in saved_tasks:
                session._record_error(task)  # pyright: ignore[reportPrivateUsage]
            assert failures == [session]
            assert tuple(session.errors) == saved_errors
            assert keyboard.release_calls == 2 and mouse.release_calls == 2
            assert not any("stopped unexpectedly" in r.getMessage() for r in caplog.records)
    finally:
        await asyncio.gather(session.stop(), return_exceptions=True)


async def test_concurrent_stop_shares_owned_task_and_cleans_once() -> None:
    keyboard = FakeKeyboard()
    mouse = FakeMouse()
    events: list[str] = []
    failures: list[FirstSliceSession] = []
    readers = {
        interface: FakeReader(make_connection().nodes[i], "hang")
        for i, interface in enumerate(("00", "01", "02"))
    }
    session = _make_session(readers, failures, keyboard, mouse, events)
    await session.start()
    try:
        assert session._stop_task is None  # pyright: ignore[reportPrivateUsage]
        first = asyncio.create_task(session.stop())
        await asyncio.sleep(0)
        owned = session._stop_task  # pyright: ignore[reportPrivateUsage]
        assert owned is not None
        second = asyncio.create_task(session.stop())
        await asyncio.sleep(0)
        assert session._stop_task is owned  # pyright: ignore[reportPrivateUsage]
        await asyncio.wait_for(asyncio.gather(first, second), 2)
        assert owned.done()
        assert failures == []
        assert all(r.stop_calls == 1 for r in readers.values())
        assert keyboard.release_calls == 1 and keyboard.close_calls == 1
        assert mouse.release_calls == 1 and mouse.close_calls == 1
        assert events.count("actions.stop") == 1
    finally:
        await asyncio.gather(session.stop(), return_exceptions=True)
