import asyncio
from threading import Event, get_ident

import pytest

from naga_control.domain.hardware import HardwareScrollMode, HardwareState, SettingsFailure
from naga_control.domain.profiles import Profile
from naga_control.ports.hardware import NagaTopology
from naga_control.service.hardware_worker import (
    HardwareQueueFullError,
    HardwareTopologyStaleError,
    HardwareWorker,
    StaleHardwareOperationError,
)


class FakeBackend:
    def __init__(self, *, block_first_move: bool = False, block_first_rescan: bool = False) -> None:
        self.block_first_move = block_first_move
        self.block_first_rescan = block_first_rescan
        self.started = Event()
        self.release = Event()
        self.calls: list[str] = []
        self.thread_ids: list[int] = []
        self._move_count = 0
        self._rescan_count = 0
        self.state = HardwareState("unavailable", 1)

    def refresh_state(self) -> HardwareState:
        self.calls.append("refresh")
        return self.state

    def rescan(self, connections: tuple[NagaTopology, ...]) -> HardwareState:
        del connections
        self._rescan_count += 1
        state = self._record("rescan")
        if self.block_first_rescan and self._rescan_count == 1:
            self.started.set()
            assert self.release.wait(timeout=2)
        return state

    def move_dpi_stage(self, direction: int) -> HardwareState:
        self._move_count += 1
        state = self._record(f"dpi:{direction}")
        if self.block_first_move and self._move_count == 1:
            self.started.set()
            assert self.release.wait(timeout=2)
        return state

    def set_scroll_mode(self, mode: HardwareScrollMode) -> HardwareState:
        return self._record(f"scroll:{mode}")

    def move_scroll_mode(self, direction: int) -> HardwareState:
        return self._record(f"scroll-move:{direction}")

    def apply_profile_settings(
        self, profile: Profile
    ) -> tuple[HardwareState, tuple[SettingsFailure, ...]]:
        return self._record("settings"), ()

    def invalidate(self) -> None:
        self._record("invalidate")

    def close(self) -> None:
        self._record("close")

    def _record(self, call: str) -> HardwareState:
        self.calls.append(call)
        self.thread_ids.append(get_ident())
        return HardwareState(status="absent", generation=len(self.calls))


async def test_worker_serializes_backend_calls_and_rejects_queued_stale_operations() -> None:
    backend = FakeBackend(block_first_move=True)
    worker = HardwareWorker(backend, queue_size=4)
    await worker.start()

    first = asyncio.create_task(worker.move_dpi_stage(1))
    await asyncio.to_thread(backend.started.wait)
    stale = asyncio.create_task(worker.move_dpi_stage(-1))
    await asyncio.sleep(0)
    rescan = asyncio.create_task(worker.rescan(()))
    backend.release.set()

    await first
    with pytest.raises(StaleHardwareOperationError):
        await stale
    await rescan
    await worker.stop()

    assert backend.calls == ["dpi:1", "rescan", "close"]
    assert len(set(backend.thread_ids)) == 1
    assert backend.thread_ids[0] != get_ident()


async def test_worker_queue_is_bounded_without_reordering_pending_operations() -> None:
    backend = FakeBackend(block_first_move=True)
    worker = HardwareWorker(backend, queue_size=1)
    await worker.start()

    first = asyncio.create_task(worker.move_dpi_stage(1))
    await asyncio.to_thread(backend.started.wait)
    second = asyncio.create_task(worker.move_dpi_stage(-1))
    await asyncio.sleep(0)

    with pytest.raises(HardwareQueueFullError):
        await worker.move_dpi_stage(1)

    backend.release.set()
    await first
    await second
    await worker.stop()

    assert backend.calls == ["dpi:1", "dpi:-1", "close"]


async def test_lifecycle_staleness_blocks_mutations_until_a_current_rescan_finishes() -> None:
    backend = FakeBackend(block_first_rescan=True)
    worker = HardwareWorker(backend)
    await worker.start()

    worker.mark_topology_stale()
    with pytest.raises(HardwareTopologyStaleError):
        await worker.move_dpi_stage(1)

    first_rescan = asyncio.create_task(worker.rescan(()))
    await asyncio.to_thread(backend.started.wait)
    worker.mark_topology_stale()
    backend.release.set()
    await first_rescan

    with pytest.raises(HardwareTopologyStaleError):
        await worker.move_dpi_stage(1)

    await worker.rescan(())
    await worker.move_dpi_stage(1)
    await worker.stop()

    assert backend.calls == ["rescan", "rescan", "dpi:1", "close"]
