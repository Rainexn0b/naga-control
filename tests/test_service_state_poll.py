import asyncio
from typing import cast

from naga_control.adapters.evdev.discovery import NagaConnection
from naga_control.domain.hardware import DeviceMode, HardwareDpiStage, HardwareState
from naga_control.service.runtime import NagaService


class Worker:
    def __init__(self) -> None:
        self.refreshed_state: HardwareState | None = None
        self.refresh_calls = 0

    async def start(self) -> None:
        return None

    def mark_topology_stale(self) -> None:
        return None

    async def rescan(self, connections: tuple[NagaConnection, ...]) -> HardwareState:
        return HardwareState(
            "available",
            1,
            transport="hyperspeed",
            dpi=HardwareDpiStage(800, 800),
            dpi_stages=(HardwareDpiStage(800, 800),),
            active_dpi_stage=1,
            max_dpi=30000,
            scroll_mode="tactile",
            scroll_mode_options=("tactile", "free_spin", "precision_tactile"),
            scroll_acceleration=False,
            scroll_smart_reel=False,
            battery_percent=90.0,
        )

    async def refresh_state(self) -> HardwareState:
        self.refresh_calls += 1
        return self.refreshed_state or HardwareState(
            "available",
            1,
            transport="hyperspeed",
            dpi=HardwareDpiStage(800, 800),
            dpi_stages=(HardwareDpiStage(800, 800),),
            active_dpi_stage=1,
            max_dpi=30000,
            scroll_mode="tactile",
            scroll_mode_options=("tactile", "free_spin", "precision_tactile"),
            scroll_acceleration=False,
            scroll_smart_reel=False,
            battery_percent=90.0,
        )

    async def read_device_mode(self) -> DeviceMode:
        return "software"

    async def set_device_mode(self, mode: DeviceMode) -> DeviceMode:
        return mode

    async def apply_profile_settings(self, profile: object) -> tuple[HardwareState, tuple[()]]:
        return HardwareState(
            "available",
            1,
            transport="hyperspeed",
            dpi=HardwareDpiStage(800, 800),
            dpi_stages=(HardwareDpiStage(800, 800),),
            active_dpi_stage=1,
            max_dpi=30000,
            scroll_mode="tactile",
            scroll_mode_options=("tactile", "free_spin", "precision_tactile"),
            scroll_acceleration=False,
            scroll_smart_reel=False,
        ), ()

    async def stop(self) -> None:
        return None


class Session:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def release_all(self) -> None:
        return None


def test_periodic_state_poll_updates_battery_without_user_action() -> None:
    asyncio.run(_exercise_state_poll())


async def _exercise_state_poll() -> None:
    worker = Worker()
    service = NagaService(
        discover=lambda: (),
        load_configuration=lambda: None,
        worker=worker,  # type: ignore[arg-type]
        session_factory=lambda connection, configuration: Session(),  # type: ignore[arg-type]
        state_poll_interval=0.01,
    )
    started = await service.start()
    assert started.battery_percent == 90.0

    worker.refreshed_state = HardwareState(
        "available",
        1,
        transport="hyperspeed",
        dpi=HardwareDpiStage(800, 800),
        dpi_stages=(HardwareDpiStage(800, 800),),
        active_dpi_stage=1,
        max_dpi=30000,
        scroll_mode="tactile",
        scroll_mode_options=("tactile", "free_spin", "precision_tactile"),
        scroll_acceleration=False,
        scroll_smart_reel=False,
        battery_percent=41.0,
    )
    await asyncio.sleep(0.08)
    snapshot: dict[str, object] = service.snapshot()
    observed = cast("dict[str, object]", snapshot["observed"])
    assert observed["battery_percent"] == 41.0
    assert worker.refresh_calls >= 1

    await service.stop()
    calls_after_stop = worker.refresh_calls
    await asyncio.sleep(0.05)
    assert worker.refresh_calls == calls_after_stop
