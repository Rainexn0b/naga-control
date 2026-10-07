import asyncio
import logging
from typing import Literal, cast

import pytest
from test_openrazer_lifecycle_monitor import FakeBus, FakeMessage

from naga_control.adapters.openrazer import lifecycle_monitor
from naga_control.adapters.openrazer.lifecycle_monitor import (
    DEVICE_ADDED_RULE,
    DEVICE_REMOVED_RULE,
    NAME_OWNER_CHANGED_RULE,
    OpenRazerLifecycleMonitor,
)
from naga_control.domain.hardware import HardwareState
from naga_control.ports.hardware import NagaTopology

LOGGER = "naga_control.adapters.openrazer.lifecycle_monitor"
PRIVATE_ERROR = "serial=PRIVATE-SERIAL usb=/sys/devices/PRIVATE-PORT token=PRIVATE-TOKEN"
type FailureSource = Literal["provider", "controller"]


class Provider:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.calls = 0

    def get_topology(self) -> tuple[NagaTopology, ...]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return ()


class Controller:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.stale_marks = 0
        self.stale = False
        self.rescans: list[tuple[NagaTopology, ...]] = []
        self.successes = 0
        self.entered = asyncio.Event()
        self.release: asyncio.Event | None = None
        self.cancelled = asyncio.Event()

    def mark_topology_stale(self) -> None:
        self.stale_marks += 1
        self.stale = True

    async def rescan(self, connections: tuple[NagaTopology, ...]) -> HardwareState:
        self.rescans.append(connections)
        self.entered.set()
        if self.release is not None:
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
        if self.error is not None:
            raise self.error
        self.successes += 1
        self.stale = False
        return HardwareState(status="absent", generation=self.successes)


def _monitor(
    bus: FakeBus, provider: Provider, controller: Controller, *, debounce: float = 0
) -> OpenRazerLifecycleMonitor:
    async def factory() -> FakeBus:
        return bus

    return OpenRazerLifecycleMonitor(
        provider, controller, bus_factory=factory, debounce_seconds=debounce
    )


def _signal(bus: FakeBus, member: str = "device_added") -> None:
    bus.emit(FakeMessage("org.razer", "/org/razer", "razer.devices", member, []))


async def _finish_rescan(monitor: OpenRazerLifecycleMonitor) -> None:
    # Await the scheduled task itself so assertions run after the catch/log boundary.
    runner = cast(asyncio.Task[None] | None, getattr(monitor, "_runner", None))
    assert runner is not None
    await asyncio.wait_for(asyncio.shield(runner), timeout=2)
    assert runner.done() and not runner.cancelled()


def _set_failure(provider: Provider, controller: Controller, source: FailureSource) -> None:
    provider.error = OSError(PRIVATE_ERROR) if source == "provider" else None
    controller.error = RuntimeError(PRIVATE_ERROR) if source == "controller" else None


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == LOGGER and record.levelno >= logging.WARNING
    ]


def _assert_safe_warning(
    record: logging.LogRecord, source: FailureSource, error_type: type[Exception] | None = None
) -> None:
    assert record.levelno == logging.WARNING
    message = record.getMessage()
    for word in ("openrazer", "lifecycle", "rescan", "failed"):
        assert word in message.lower()
    phase = "topology discovery" if source == "provider" else "controller rescan"
    assert phase in message.lower()
    if error_type is None:
        error_type = OSError if source == "provider" else RuntimeError
    assert error_type.__name__ in message
    for secret in (PRIVATE_ERROR, "PRIVATE-SERIAL", "PRIVATE-PORT", "PRIVATE-TOKEN"):
        assert secret not in repr(record.__dict__)
    assert record.exc_info is None
    assert record.exc_text is None
    assert record.stack_info is None


@pytest.mark.parametrize("source", ["provider", "controller"])
async def test_rescan_failure_warns_safely_and_later_signal_recovers(
    source: FailureSource, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger=LOGGER)
    bus, provider, controller = FakeBus(), Provider(), Controller()
    _set_failure(provider, controller, source)
    monitor = _monitor(bus, provider, controller)
    try:
        await monitor.start()
        await _finish_rescan(monitor)
        assert controller.stale
        assert provider.calls == 1
        assert controller.rescans == ([] if source == "provider" else [()])
        assert controller.successes == 0
        assert len(_warnings(caplog)) == 1
        _assert_safe_warning(_warnings(caplog)[0], source)

        provider.error = controller.error = None
        _signal(bus, "device_removed")
        assert controller.stale_marks == 2
        assert provider.calls == 1
        await _finish_rescan(monitor)
        assert provider.calls == 2
        assert controller.successes == 1
        assert not controller.stale
        assert len(_warnings(caplog)) == 1
    finally:
        await asyncio.wait_for(monitor.stop(), timeout=2)


@pytest.mark.parametrize("source", ["provider", "controller"])
async def test_failure_streak_warns_once_per_phase_and_type_until_complete_recovery(
    source: FailureSource, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger=LOGGER)
    bus, provider, controller = FakeBus(), Provider(), Controller()
    other: FailureSource = "controller" if source == "provider" else "provider"
    _set_failure(provider, controller, source)
    monitor = _monitor(bus, provider, controller)
    try:
        await monitor.start()
        await _finish_rescan(monitor)
        assert len(_warnings(caplog)) == 1
        _assert_safe_warning(_warnings(caplog)[0], source)

        # Successful discovery alone must not reset controller-failure suppression.
        failures: tuple[tuple[FailureSource, int], ...] = (
            (source, 1),
            (other, 2),
            (other, 2),
            (source, 2),
        )
        for failure, warning_count in failures:
            _set_failure(provider, controller, failure)
            _signal(bus)
            await _finish_rescan(monitor)
            assert controller.stale
            assert controller.successes == 0
            assert len(_warnings(caplog)) == warning_count
        _assert_safe_warning(_warnings(caplog)[1], other)

        provider.error = controller.error = None
        _signal(bus)
        await _finish_rescan(monitor)
        assert controller.successes == 1
        assert not controller.stale
        assert len(_warnings(caplog)) == 2

        _set_failure(provider, controller, source)
        _signal(bus)
        await _finish_rescan(monitor)
        assert controller.stale
        assert provider.calls == 7
        assert controller.stale_marks == 7
        assert controller.successes == 1
        assert len(_warnings(caplog)) == 3
        _assert_safe_warning(_warnings(caplog)[2], source)
    finally:
        await asyncio.wait_for(monitor.stop(), timeout=2)


@pytest.mark.parametrize(
    ("source", "error_type"), [("controller", RuntimeError), ("provider", ValueError)]
)
async def test_distinct_phase_or_exception_class_warns_without_complete_recovery(
    source: FailureSource, error_type: type[Exception], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger=LOGGER)
    bus, provider, controller = FakeBus(), Provider(), Controller()
    provider.error = RuntimeError(PRIVATE_ERROR)
    monitor = _monitor(bus, provider, controller)
    try:
        await monitor.start()
        await _finish_rescan(monitor)
        assert len(_warnings(caplog)) == 1
        _assert_safe_warning(_warnings(caplog)[0], "provider", RuntimeError)

        for failure_source, failure_type in (
            (source, error_type),
            (source, error_type),
            ("provider", RuntimeError),
        ):
            provider.error = failure_type(PRIVATE_ERROR) if failure_source == "provider" else None
            controller.error = (
                failure_type(PRIVATE_ERROR) if failure_source == "controller" else None
            )
            _signal(bus)
            await _finish_rescan(monitor)
            assert controller.stale
            assert controller.successes == 0
            assert len(_warnings(caplog)) == 2
        _assert_safe_warning(_warnings(caplog)[1], source, error_type)
        assert provider.calls == 4
        assert controller.stale_marks == 4
    finally:
        await asyncio.wait_for(monitor.stop(), timeout=2)


async def test_stop_cancels_in_flight_rescan_without_warning_and_detaches_listeners(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=LOGGER)
    bus, provider, controller = FakeBus(), Provider(), Controller()
    controller.release = asyncio.Event()
    monitor = _monitor(bus, provider, controller)
    try:
        await monitor.start()
        await asyncio.wait_for(controller.entered.wait(), timeout=2)
        runner = cast(asyncio.Task[None] | None, getattr(monitor, "_runner", None))
        assert runner is not None
        assert not runner.done()
        await asyncio.wait_for(monitor.stop(), timeout=2)
        assert controller.cancelled.is_set()
        assert runner.cancelled()
        assert controller.successes == 0
        assert bus.handlers == []
        assert bus.removed_rules == [
            NAME_OWNER_CHANGED_RULE,
            DEVICE_REMOVED_RULE,
            DEVICE_ADDED_RULE,
        ]
        assert bus.disconnected
        _signal(bus)
        assert controller.stale_marks == 1
        assert provider.calls == 1
        assert _warnings(caplog) == []
    finally:
        await asyncio.wait_for(monitor.stop(), timeout=2)


async def test_failure_recovery_keeps_immediate_fencing_and_debounces_signal_bursts(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger=LOGGER)
    entered, release = asyncio.Event(), asyncio.Event()
    delays: list[float] = []

    async def controlled_debounce(delay: float) -> None:
        delays.append(delay)
        entered.set()
        await release.wait()

    monkeypatch.setattr(lifecycle_monitor.asyncio, "sleep", controlled_debounce)
    bus, provider, controller = FakeBus(), Provider(), Controller()
    provider.error = OSError(PRIVATE_ERROR)
    monitor = _monitor(bus, provider, controller, debounce=0.25)
    try:
        await monitor.start()
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert provider.calls == 0
        assert controller.stale_marks == 1
        release.set()
        await _finish_rescan(monitor)

        entered.clear()
        release.clear()
        provider.error = None
        _signal(bus)
        _signal(bus, "device_removed")
        bus.emit(
            FakeMessage(
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "NameOwnerChanged",
                ["org.razer", "old-owner", "new-owner"],
            )
        )
        assert controller.stale_marks == 4
        assert controller.stale
        assert provider.calls == 1
        assert controller.rescans == []
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert provider.calls == 1
        release.set()
        await _finish_rescan(monitor)
        assert delays == [0.25, 0.25]
        assert provider.calls == 2
        assert controller.rescans == [()]
        assert controller.successes == 1
        assert not controller.stale
        assert len(_warnings(caplog)) == 1
        _assert_safe_warning(_warnings(caplog)[0], "provider")
    finally:
        await asyncio.wait_for(monitor.stop(), timeout=2)
