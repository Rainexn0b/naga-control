"""Redacted reader-failure warnings: fixed tokens, no identifiers."""

import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress

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
        self.stopped = False

    def start(self) -> None:
        return None

    async def run(self) -> object:
        if self.mode == "hang":
            await asyncio.Event().wait()
            return SourceReadResult(None)
        assert self.error is not None
        raise self.error

    def stop(self) -> None:
        self.stopped = True


class _ProxyFactory:
    def create(self, spec: ForwardingProxySpec) -> ForwardingProxy:
        raise AssertionError("redaction tests use fake readers")


class _Waiter:
    def wait_ready(self, spec: ForwardingProxySpec) -> None:
        raise AssertionError("redaction tests use fake readers")


async def _wait_for(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    await asyncio.wait_for(_poll(predicate), timeout)


async def _poll(predicate: Callable[[], bool]) -> None:
    while not predicate():
        await asyncio.sleep(0.01)


def _session_with(
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
        _p: object,
        _k: object,
        _m: object,
        _d: object,
        _f: object,
        _w: object,
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


@pytest.mark.parametrize(
    "value,expected",
    [
        ("00", "00"),
        ("01", "01"),
        ("02", "02"),
        ("03", "unknown"),
        ("bogus", "unknown"),
        (None, "unknown"),
        (1, "unknown"),
        (b"01", "unknown"),
    ],
)
def test_sanitized_interface_allows_only_fixed_tokens(value: object, expected: str) -> None:
    from naga_control.application import remapping as remapping_module

    assert remapping_module._sanitized_interface(value) == expected  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (19, 19),
        (1, 1),
        (4095, 4095),
        (0, None),
        (4096, None),
        (-1, None),
        (None, None),
        ("19", None),
        (True, None),
        (False, None),
    ],
)
def test_sanitized_errno_accepts_only_exact_builtin_int_range(
    raw: object, expected: int | None
) -> None:
    from naga_control.application import remapping as remapping_module

    error = OSError("private message SERIAL-/sys/PRIVATE-USB-event5")
    error.errno = raw  # type: ignore[assignment]

    class SubInt(int):
        pass

    if isinstance(raw, int) and not isinstance(raw, bool) and raw == 19:
        sub = OSError("private")
        sub.errno = SubInt(19)  # type: ignore[assignment]
        assert remapping_module._sanitized_errno(sub) is None  # pyright: ignore[reportPrivateUsage]
    assert remapping_module._sanitized_errno(error) == expected  # pyright: ignore[reportPrivateUsage]


async def test_error_warning_redacts_private_message_and_chain(
    caplog: pytest.LogCaptureFixture,
) -> None:
    keyboard = FakeKeyboard()
    mouse = FakeMouse()
    events: list[str] = []
    failures: list[FirstSliceSession] = []
    private = OSError("SERIAL-PRIVATE /sys/PRIVATE-USB event5 failure")
    private.errno = 19
    private.__cause__ = ValueError("PRIVATE-CAUSE chain")
    private.__context__ = RuntimeError("PRIVATE-CONTEXT chain")
    readers = {
        "00": FakeReader(make_connection().nodes[0], "hang"),
        "01": FakeReader(make_connection().nodes[1], "raise", private),
        "02": FakeReader(make_connection().nodes[2], "hang"),
    }
    session = _session_with(readers, failures, keyboard, mouse, events)
    try:
        with caplog.at_level(logging.WARNING):
            await session.start()
            await _wait_for(lambda: keyboard.released)
            assert failures == [session]
            warning = next(r for r in caplog.records if "stopped unexpectedly" in r.getMessage())
            assert "interface=01" in warning.getMessage()
            assert "outcome=error" in warning.getMessage()
            assert "error=OSError" in warning.getMessage()
            assert "errno=19" in warning.getMessage()
            assert warning.exc_info is None and warning.exc_text is None
            assert warning.stack_info is None
            for secret in ("SERIAL", "/sys/", "event5", "PRIVATE", "chain", "CAUSE", "CONTEXT"):
                assert secret not in caplog.text
    finally:
        await asyncio.gather(session.stop(), return_exceptions=True)


async def test_cancel_warning_has_no_errno_and_no_identifiers(
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
    session = _session_with(readers, failures, keyboard, mouse, events)
    try:
        with caplog.at_level(logging.WARNING):
            await session.start()
            task = session._tasks[0]  # pyright: ignore[reportPrivateUsage]
            task.cancel()
            await _wait_for(lambda: keyboard.released)
            assert failures == [session]
            warning = next(r for r in caplog.records if "stopped unexpectedly" in r.getMessage())
            assert "interface=00" in warning.getMessage()
            assert "outcome=cancel" in warning.getMessage()
            assert "error=CancelledError" in warning.getMessage()
            assert "errno=" not in warning.getMessage()
            assert warning.exc_info is None and warning.exc_text is None
    finally:
        await asyncio.gather(session.stop(), return_exceptions=True)


async def test_unknown_interface_warning_when_task_not_mapped(
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
    session = _session_with(readers, failures, keyboard, mouse, events)
    try:
        with caplog.at_level(logging.WARNING):
            await session.start()

            async def _boom() -> object:
                raise OSError(5, "SERIAL-PRIVATE /sys/PRIVATE event5")

            dummy = asyncio.create_task(_boom())
            with suppress(BaseException):
                await asyncio.gather(dummy, return_exceptions=True)
            session._record_error(dummy)  # pyright: ignore[reportPrivateUsage]
            await _wait_for(lambda: keyboard.released)
            assert failures == [session]
            warning = next(r for r in caplog.records if "stopped unexpectedly" in r.getMessage())
            assert "interface=unknown" in warning.getMessage()
            assert "outcome=error" in warning.getMessage()
            for secret in ("SERIAL", "/sys/", "event5", "PRIVATE"):
                assert secret not in caplog.text
    finally:
        await asyncio.gather(session.stop(), return_exceptions=True)
