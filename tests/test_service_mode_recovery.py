import asyncio
from collections.abc import Callable
from dataclasses import replace

from test_service_mode import Session, Worker, available, service_for

from naga_control.domain.hardware import DeviceMode, DeviceModeError, HardwareState
from naga_control.ports.hardware import NagaTopology
from naga_control.service.hardware_worker import HardwareTopologyStaleError


async def _wait_until(condition: Callable[[], bool]) -> None:
    async def wait() -> None:
        while not condition():
            await asyncio.sleep(0.002)

    await asyncio.wait_for(wait(), timeout=1)


async def test_unavailable_start_recovers_without_udev_or_daemon_signal() -> None:
    events: list[str] = []
    worker = Worker(events)
    worker.state = HardwareState("unavailable", 1)
    sessions: list[Session] = []
    service = service_for(worker, sessions, poll=0.01)
    try:
        await service.start()
        assert sessions == []
        worker.state = replace(available(), generation=2)
        await _wait_until(lambda: service.snapshot()["mode_ready"] is True)
        assert len(sessions) == 1
        assert events.count("rescan") >= 2
    finally:
        await service.stop()


async def test_transient_mode_read_failure_releases_then_rebuilds_software() -> None:
    events: list[str] = []
    worker = Worker(events)
    sessions: list[Session] = []
    service = service_for(worker, sessions, poll=0.01)
    try:
        await service.start()
        worker.read_error = DeviceModeError("read_failed", "wireless asleep")
        await asyncio.wait_for(sessions[0].stopping.wait(), timeout=1)
        assert service.snapshot()["mode_ready"] is False
        worker.read_error = None
        await _wait_until(lambda: service.snapshot()["mode_ready"] is True)
        assert len(sessions) == 2
        assert events.index("read", events.index("session.stop")) < events.index(
            "session.start", events.index("session.stop")
        )
    finally:
        await service.stop()


async def test_transient_read_failure_rescans_a_fenced_worker() -> None:
    class FencedWorker(Worker):
        stale = False

        def mark_topology_stale(self) -> None:
            super().mark_topology_stale()
            self.stale = True

        async def rescan(self, connections: tuple[NagaTopology, ...]) -> HardwareState:
            state = await super().rescan(connections)
            self.stale = False
            return state

        async def read_device_mode(self) -> DeviceMode:
            if self.stale:
                raise HardwareTopologyStaleError("hardware topology rescan is pending")
            return await super().read_device_mode()

    events: list[str] = []
    worker = FencedWorker(events)
    sessions: list[Session] = []
    service = service_for(worker, sessions, poll=0.01)
    try:
        await service.start()
        worker.read_error = DeviceModeError("read_failed", "wireless asleep")
        await asyncio.wait_for(sessions[0].stopping.wait(), timeout=1)
        assert service.snapshot()["mode_ready"] is False
        worker.read_error = None
        await _wait_until(lambda: service.snapshot()["mode_ready"] is True)
        assert events.count("rescan") >= 2
        assert len(sessions) == 2
    finally:
        await service.stop()


async def test_unavailable_device_action_fences_and_releases_held_output() -> None:
    events: list[str] = []
    worker = Worker(events)
    sessions: list[Session] = []
    service = service_for(worker, sessions, poll=0.01)
    try:
        await service.start()
        service.record_hardware_state(HardwareState("unavailable", 2, transport="hyperspeed"))
        assert events[-2:] == ["stale", "session.release"]
        assert service.snapshot()["mode_ready"] is False
        await asyncio.wait_for(sessions[0].stopping.wait(), timeout=1)
        worker.state = replace(available(), generation=3)
        await _wait_until(lambda: service.snapshot()["mode_ready"] is True)
        assert len(sessions) == 2
        assert (
            events.index("session.release")
            < events.index("session.stop")
            < events.index("session.start", events.index("session.stop"))
        )
    finally:
        await service.stop()


async def test_lifecycle_signal_releases_even_when_provider_never_rescans() -> None:
    events: list[str] = []
    worker = Worker(events)
    sessions: list[Session] = []
    service = service_for(worker, sessions, poll=0.01)
    try:
        await service.start()
        service.mark_topology_stale()
        assert events[-2:] == ["stale", "session.release"]
        await asyncio.wait_for(sessions[0].stopping.wait(), timeout=1)
        await _wait_until(lambda: service.snapshot()["mode_ready"] is True)
        assert len(sessions) == 2
        assert events.count("rescan") >= 2
    finally:
        await service.stop()
