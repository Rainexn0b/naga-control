"""Reusable hardware worker, session, and topology doubles for runtime tests."""

from naga_control.adapters.evdev.discovery import EventNode, NagaConnection
from naga_control.domain.hardware import (
    DeviceMode,
    HardwareDpiStage,
    HardwareState,
    SettingsFailure,
)
from naga_control.domain.profiles import Profile
from naga_control.ports.hardware import NagaTopology


class Worker:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.applied: list[object] = []
        self.settings_failures: tuple[SettingsFailure, ...] = ()
        self.rescan_state: HardwareState | None = None
        self.mode: DeviceMode = "software"

    async def start(self) -> None:
        self.events.append("start")

    def mark_topology_stale(self) -> None:
        self.events.append("stale")

    async def rescan(self, connections: tuple[NagaTopology, ...]) -> HardwareState:
        self.events.append(f"rescan:{len(connections)}")
        if self.rescan_state is not None:
            return self.rescan_state
        return available()

    async def read_device_mode(self) -> DeviceMode:
        self.events.append("read_mode")
        return self.mode

    async def set_device_mode(self, mode: DeviceMode) -> DeviceMode:
        self.events.append(f"set_mode:{mode}")
        self.mode = mode
        return mode

    async def refresh_state(self) -> HardwareState:
        return available()

    async def apply_profile_settings(
        self, profile: Profile
    ) -> tuple[HardwareState, tuple[SettingsFailure, ...]]:
        self.events.append("settings")
        self.applied.append(profile)
        return available(), self.settings_failures

    async def stop(self) -> None:
        self.events.append("stop")


class Session:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def start(self) -> None:
        self.events.append("start")

    async def stop(self) -> None:
        self.events.append("stop")

    def release_all(self) -> None:
        self.events.append("release")


class Store:
    def __init__(self) -> None:
        self.saved: list[object] = []

    def load(self) -> None:
        return None

    def save(self, configuration: object) -> None:
        self.saved.append(configuration)


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
