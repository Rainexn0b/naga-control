import asyncio
from dataclasses import replace

import pytest

from naga_control.adapters.evdev.discovery import EventNode, NagaConnection
from naga_control.config import dump_toml
from naga_control.domain.defaults import default_configuration
from naga_control.domain.hardware import (
    DeviceMode,
    DeviceModeError,
    HardwareDpiStage,
    HardwareState,
)
from naga_control.domain.profiles import Profile
from naga_control.ports.hardware import NagaTopology
from naga_control.service.runtime import NagaService, StaleConfigurationRevisionError


def connection() -> NagaConnection:
    node = EventNode("/dev/input/event5", "/sys/usb", "01", "1532", "00e8")
    return NagaConnection("/sys/usb", "1532", "00e8", "hyperspeed", None, None, (node,))


def available() -> HardwareState:
    stage = HardwareDpiStage(800, 800)
    return HardwareState(
        "available",
        1,
        transport="hyperspeed",
        dpi=stage,
        dpi_stages=(stage,),
        active_dpi_stage=1,
        max_dpi=30000,
        scroll_mode="tactile",
        scroll_mode_options=("tactile",),
        scroll_acceleration=False,
        scroll_smart_reel=False,
    )


class Worker:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.mode: DeviceMode = "software"
        self.state = available()
        self.settings_state: HardwareState | None = None
        self.read_error: DeviceModeError | None = None
        self.write_error: DeviceModeError | None = None
        self.rescan_error: RuntimeError | None = None
        self.rescan_gate: asyncio.Event | None = None
        self.rescan_entered = asyncio.Event()
        self.read_gate: asyncio.Event | None = None
        self.read_entered = asyncio.Event()
        self.writes = 0

    async def start(self) -> None:
        self.events.append("worker.start")

    def mark_topology_stale(self) -> None:
        self.events.append("stale")

    async def rescan(self, connections: tuple[NagaTopology, ...]) -> HardwareState:
        self.events.append("rescan")
        self.rescan_entered.set()
        if self.rescan_gate is not None:
            await self.rescan_gate.wait()
        if self.rescan_error is not None:
            raise self.rescan_error
        return self.state

    async def read_device_mode(self) -> DeviceMode:
        self.events.append("read")
        self.read_entered.set()
        if self.read_gate is not None:
            await self.read_gate.wait()
        if self.read_error is not None:
            raise self.read_error
        return self.mode

    async def set_device_mode(self, mode: DeviceMode) -> DeviceMode:
        self.events.append(f"write:{mode}")
        self.writes += 1
        if self.write_error is not None:
            raise self.write_error
        self.mode = mode
        return mode

    async def apply_profile_settings(self, profile: Profile) -> tuple[HardwareState, tuple[()]]:
        self.events.append("settings")
        return self.settings_state or self.state, ()

    async def refresh_state(self) -> HardwareState:
        self.events.append("refresh")
        return self.state

    async def stop(self) -> None:
        self.events.append("worker.stop")


class Session:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.stop_gate: asyncio.Event | None = None
        self.stopping = asyncio.Event()

    async def start(self) -> None:
        self.events.append("session.start")

    async def stop(self) -> None:
        self.events.append("session.stop")
        self.stopping.set()
        if self.stop_gate is not None:
            await self.stop_gate.wait()

    def release_all(self) -> None:
        self.events.append("session.release")


def service_for(
    worker: Worker, sessions: list[Session], *, mode: DeviceMode = "software", poll: float = 30.0
) -> NagaService:
    def factory(connection: NagaConnection, configuration: object) -> Session:
        session = Session(worker.events)
        sessions.append(session)
        return session

    return NagaService(
        lambda: (connection(),),
        lambda: replace(default_configuration(), mode=mode),
        worker,
        factory,
        state_poll_interval=poll,
    )


async def test_firmware_start_and_software_transition_order() -> None:
    events: list[str] = []
    worker = Worker(events)
    sessions: list[Session] = []
    service = service_for(worker, sessions, mode="firmware")
    await service.start()
    assert events == ["worker.start", "rescan", "read", "write:firmware"]
    assert sessions == []
    assert service.snapshot()["mode_ready"] is True
    with pytest.raises(RuntimeError, match="calibration requires software"):
        await service.begin_calibration()
    await service.apply_configuration(
        0, dump_toml(replace(default_configuration(), revision=1, mode="software"))
    )
    assert events[-5:] == ["rescan", "read", "write:software", "settings", "session.start"]
    assert service.snapshot()["observed_mode"] == "software"
    await service.stop()


async def test_mode_switch_fences_actions_and_closes_session_before_write() -> None:
    events: list[str] = []
    worker = Worker(events)
    sessions: list[Session] = []
    service = service_for(worker, sessions)
    await service.start()
    gate = asyncio.Event()
    sessions[0].stop_gate = gate
    transition = asyncio.create_task(
        service.apply_configuration(
            0, dump_toml(replace(default_configuration(), revision=1, mode="firmware"))
        )
    )
    await sessions[0].stopping.wait()
    assert events[-2:] == ["stale", "session.stop"]
    assert worker.writes == 0
    gate.set()
    await transition
    assert events[-3:] == ["rescan", "read", "write:firmware"]
    assert len(sessions) == 1
    assert service.snapshot()["settings_failures"] == []
    await service.stop()


@pytest.mark.parametrize("failure", ["unavailable", "read_failed", "write_failed"])
async def test_unknown_mode_never_grabs_or_retries_on_poll(failure: str) -> None:
    events: list[str] = []
    worker = Worker(events)
    sessions: list[Session] = []
    if failure == "unavailable":
        worker.state = HardwareState("unavailable", 1)
    elif failure == "read_failed":
        worker.read_error = DeviceModeError("read_failed", "mode read timed out")
    else:
        worker.mode = "firmware"
        worker.write_error = DeviceModeError("write_failed", "mode write uncertain")
    service = service_for(worker, sessions, poll=0.01)
    await service.start()
    assert sessions == []
    assert service.snapshot()["status"] == "unavailable"
    assert service.snapshot()["mode_ready"] is False
    assert service.snapshot()["mode_error"]
    await asyncio.sleep(0.05)
    assert worker.writes <= 1
    assert sessions == []
    await service.stop()


async def test_lifecycle_reassertion_and_poll_drift_fail_open() -> None:
    events: list[str] = []
    worker = Worker(events)
    sessions: list[Session] = []
    service = service_for(worker, sessions, mode="firmware", poll=0.01)
    await service.start()
    worker.mode = "software"
    await service.rescan((connection(),))
    assert events[-3:] == ["rescan", "read", "write:firmware"]
    assert sessions == []
    worker.mode = "software"
    await asyncio.sleep(0.05)
    assert service.snapshot()["status"] == "available"
    assert service.snapshot()["observed_mode"] == "firmware"
    assert service.snapshot()["mode_ready"] is True
    assert worker.writes == 3
    await service.stop()


async def test_firmware_poll_does_not_repeat_an_uncertain_write() -> None:
    events: list[str] = []
    worker = Worker(events)
    service = service_for(worker, [], mode="firmware", poll=0.01)
    await service.start()
    worker.mode = "software"
    worker.write_error = DeviceModeError("write_failed", "acknowledgement lost")
    await asyncio.sleep(0.05)
    assert service.snapshot()["mode_ready"] is False
    assert worker.writes == 2

    worker.write_error = None
    await asyncio.sleep(0.05)
    assert worker.writes == 2
    assert service.snapshot()["mode_ready"] is False
    await service.rescan((connection(),))
    assert worker.writes == 3
    assert service.snapshot()["mode_ready"] is True
    await service.stop()


async def test_poll_drift_releases_session_then_rebuilds_after_mode_verification() -> None:
    events: list[str] = []
    worker = Worker(events)
    sessions: list[Session] = []
    service = service_for(worker, sessions, poll=0.01)
    await service.start()
    worker.mode = "firmware"
    await asyncio.sleep(0.05)
    assert events.index("stale") < events.index("session.stop")
    assert service.snapshot()["status"] == "available"
    assert worker.writes == 1
    assert len(sessions) == 2
    await service.stop()


async def test_stop_waits_for_in_flight_transition_and_revision_race() -> None:
    events: list[str] = []
    worker = Worker(events)
    sessions: list[Session] = []
    service = service_for(worker, sessions)
    await service.start()
    worker.rescan_gate = asyncio.Event()
    worker.rescan_entered.clear()
    document = dump_toml(replace(default_configuration(), revision=1, mode="firmware"))
    transition = asyncio.create_task(service.apply_configuration(0, document))
    await worker.rescan_entered.wait()
    second = asyncio.create_task(service.apply_configuration(0, document))
    stopping = asyncio.create_task(service.stop())
    await asyncio.sleep(0)
    assert not stopping.done()
    assert "worker.stop" not in events
    worker.rescan_gate.set()
    await transition
    with pytest.raises(StaleConfigurationRevisionError):
        await second
    await stopping
    assert events.index("write:firmware") < events.index("worker.stop")


async def test_mode_write_waits_for_queued_worker_work_after_grab_release() -> None:
    events: list[str] = []
    worker = Worker(events)
    sessions: list[Session] = []
    service = service_for(worker, sessions)
    await service.start()
    worker.rescan_gate = asyncio.Event()
    worker.rescan_entered.clear()
    transition = asyncio.create_task(
        service.apply_configuration(
            0, dump_toml(replace(default_configuration(), revision=1, mode="firmware"))
        )
    )
    await worker.rescan_entered.wait()
    assert events.index("stale") < events.index("session.stop") < events.index("rescan", 2)
    assert worker.writes == 0
    worker.rescan_gate.set()  # Fake worker has now drained its in-flight and queued work.
    await transition
    assert events.index("write:firmware") > events.index("rescan", 2)
    await service.stop()


async def test_poll_cannot_publish_after_a_configuration_transition() -> None:
    events: list[str] = []
    worker = Worker(events)
    sessions: list[Session] = []
    service = service_for(worker, sessions, poll=0.01)
    await service.start()
    worker.read_gate = asyncio.Event()
    worker.read_entered.clear()
    await worker.read_entered.wait()  # Poll owns the service lock while waiting for hardware.
    change = asyncio.create_task(
        service.apply_configuration(
            0, dump_toml(replace(default_configuration(), revision=1, mode="firmware"))
        )
    )
    await asyncio.sleep(0)
    assert not change.done()
    worker.read_gate.set()
    await change
    await asyncio.sleep(0.04)
    snapshot = service.snapshot()
    assert snapshot["desired_mode"] == snapshot["observed_mode"] == "firmware"
    assert snapshot["mode_ready"] is True
    assert len(sessions) == 1
    await service.stop()


async def test_failed_lifecycle_rescan_releases_the_existing_session() -> None:
    events: list[str] = []
    worker = Worker(events)
    sessions: list[Session] = []
    service = service_for(worker, sessions)
    await service.start()
    worker.rescan_error = RuntimeError("daemon disappeared")
    with pytest.raises(RuntimeError, match="daemon disappeared"):
        await service.rescan((connection(),))
    assert events[-3:] == ["stale", "session.stop", "rescan"]
    assert service.snapshot()["mode_ready"] is False
    assert "daemon disappeared" in str(service.snapshot()["mode_error"])
    await service.stop()


async def test_profile_settings_losing_hardware_never_starts_or_retains_grabs() -> None:
    events: list[str] = []
    worker = Worker(events)
    worker.settings_state = HardwareState("unavailable", 1)
    sessions: list[Session] = []
    service = service_for(worker, sessions)
    await service.start()
    assert sessions == []
    assert service.snapshot()["mode_ready"] is False

    worker.settings_state = None
    await service.apply_topology((connection(),))
    assert len(sessions) == 1
    worker.settings_state = HardwareState("unavailable", 2)
    await service.rescan((connection(),))
    assert events[-5:] == ["stale", "session.stop", "rescan", "read", "settings"]
    assert len(sessions) == 1
    assert service.snapshot()["mode_ready"] is False
    await service.stop()


async def test_failed_reader_activation_clears_session_and_reports_unready() -> None:
    events: list[str] = []
    worker = Worker(events)

    class FailingSession(Session):
        async def start(self) -> None:
            raise RuntimeError("physical keys are held")

    failed = FailingSession(events)
    service = NagaService(
        lambda: (connection(),),
        lambda: default_configuration(),
        worker,
        lambda _connection, _configuration: failed,
    )
    with pytest.raises(RuntimeError, match="physical keys are held"):
        await service.start()
    assert "session.stop" in events
    assert service.snapshot()["mode_ready"] is False
    assert "physical keys are held" in str(service.snapshot()["mode_error"])
