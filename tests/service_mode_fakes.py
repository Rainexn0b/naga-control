"""Concrete Worker/Session doubles for service mode tests."""

import asyncio
from dataclasses import replace

from naga_control.adapters.evdev.discovery import EventNode, NagaConnection
from naga_control.domain.defaults import default_configuration
from naga_control.domain.hardware import (
    DeviceMode,
    DeviceModeError,
    HardwareDpiStage,
    HardwareState,
)
from naga_control.domain.profiles import Profile
from naga_control.ports.hardware import NagaTopology
from naga_control.service.runtime import NagaService


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
