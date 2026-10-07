"""Real service/worker fencing with fake hardware, not physical-release proof."""

import asyncio
from threading import get_ident

import pytest
from test_hardware_worker import FakeBackend
from test_hardware_worker_failures import executor_of
from test_service_mode import available, connection
from test_service_session_barrier import BarrierSession, bounded

from naga_control.adapters.evdev.discovery import NagaConnection
from naga_control.domain.defaults import default_configuration
from naga_control.domain.hardware import DeviceMode, HardwareState
from naga_control.domain.profiles import Configuration
from naga_control.service.hardware_worker import HardwareTopologyStaleError, HardwareWorker
from naga_control.service.runtime import NagaService


class AvailableBackend(FakeBackend):
    def __init__(self) -> None:
        super().__init__()
        self.state = available()

    def _record(self, call: str) -> HardwareState:
        super()._record(call)
        return self.state

    def read_device_mode(self) -> DeviceMode:
        self._record("mode:read")
        return "software"


@pytest.mark.integration
@pytest.mark.parametrize("transition", ["apply_topology", "rescan"])
async def test_failed_session_cleanup_keeps_actual_worker_fenced_until_shutdown(
    transition: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = asyncio.all_tasks()
    backend = AvailableBackend()
    worker = HardwareWorker(backend)  # Explicit injection: no physical backend/discovery.
    executor = executor_of(worker)
    shutdown_calls: list[bool] = []
    original_shutdown = executor.shutdown

    def shutdown(wait: bool = True, *, cancel_futures: bool = False) -> None:
        shutdown_calls.append(wait)
        original_shutdown(wait=wait, cancel_futures=cancel_futures)

    monkeypatch.setattr(executor, "shutdown", shutdown)
    events: list[str] = []
    sessions: list[BarrierSession] = []

    def factory(_: NagaConnection, configuration: Configuration) -> BarrierSession:
        session = BarrierSession(events)
        sessions.append(session)
        return session

    service = NagaService(lambda: (connection(),), default_configuration, worker, factory)
    pending: asyncio.Task[HardwareState] | None = None
    try:
        assert await bounded(service.start()) == available()
        assert service.snapshot()["mode_ready"] is True
        assert backend.calls == ["rescan", "mode:read", "settings"]
        # Positive controls show these mutations work before service detachment.
        assert await bounded(worker.move_dpi_stage(1)) == available()
        assert await bounded(worker.set_scroll_mode("free_spin")) == available()
        assert await bounded(worker.set_device_mode("software")) == "software"
        before = list(backend.calls)
        assert before == [
            "rescan",
            "mode:read",
            "settings",
            "dpi:1",
            "scroll:free_spin",
            "mode:set:software",
        ]
        assert len(set(backend.thread_ids)) == 1
        assert backend.thread_ids[0] != get_ident()
        session = sessions[0]
        error = session.error = OSError("fake session cleanup failed")
        session.stop_gate = asyncio.Event()
        request = service.apply_topology if transition == "apply_topology" else service.rescan
        pending = asyncio.create_task(request((connection(),)))
        await bounded(session.stopping.wait())
        assert not pending.done()

        for cleanup_completed in (False, True):
            if cleanup_completed:
                session.stop_gate.set()
                with pytest.raises(OSError) as raised:
                    await bounded(pending)
                assert raised.value is error
                assert session.completed.is_set()
            for mutation in (
                lambda: worker.move_dpi_stage(-1),
                lambda: worker.set_scroll_mode("tactile"),
                lambda: worker.set_device_mode("firmware"),
            ):
                with pytest.raises(HardwareTopologyStaleError):
                    await bounded(mutation())
                assert backend.calls == before
            assert service.snapshot()["mode_ready"] is False

        # Neither recovery entry point may rescan (which would clear the fence).
        for recover in (service.apply_topology, service.rescan):
            for _ in range(2):
                with pytest.raises(OSError) as rejected:
                    await bounded(recover((connection(),)))
                assert rejected.value is error
                assert backend.calls == before
                assert sessions == [session]
                assert events == ["session.start", "session.stop", "session.stopped"]
        assert shutdown_calls == []
        with pytest.raises(OSError) as stopped:
            await bounded(service.stop())
        assert stopped.value is error
        assert backend.calls == [*before, "close"]
        assert shutdown_calls == [False]
        with pytest.raises(RuntimeError, match="cannot schedule new futures after shutdown"):
            executor.submit(lambda: None)
        await bounded(asyncio.gather(service.stop(), return_exceptions=True))
        await bounded(worker.stop())
        assert backend.calls == [*before, "close"]
        assert shutdown_calls == [False]
        assert events.count("session.stop") == 1
    finally:
        for session in sessions:
            if session.stop_gate is not None:
                session.stop_gate.set()
        if pending is not None:
            await bounded(asyncio.gather(pending, return_exceptions=True))
        await bounded(asyncio.gather(service.stop(), return_exceptions=True))
        await bounded(asyncio.gather(worker.stop(), return_exceptions=True))
        assert not (asyncio.all_tasks() - baseline)
