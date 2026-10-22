"""Exit flush barrier: deferred wake, bounded public roundtrip, isolation probe.

The CLI defers the Exit wake with ``loop.call_soon`` so the async D-Bus
handler queues its reply first, then performs one bounded public roundtrip
after resource cleanup and before disconnect. Fakes are reused from the
shutdown integration module; the final test runs the real
``service_cli.run`` and the real helper ``stop`` on a private
``dbus-run-session`` bus with a fake lifecycle only.
"""

import asyncio
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from dbus_next.constants import ReleaseNameReply
from test_service_shutdown import FakeBus, FakeService, call, start_running
from test_service_shutdown import stop_task as join_task

from naga_control.ipc.service import BUS_NAME
from naga_control.service import service_cli


class FlushBus(FakeBus):
    """Shutdown fake plus the optional public release_name capability."""

    def __init__(self, events: list[str]) -> None:
        super().__init__(events)
        self.release_error: Exception | None = None
        self.release_hang = False
        self.disconnect_error: Exception | None = None

    async def release_name(self, name: str) -> object:
        self.events.append(f"release:{name}")
        if self.release_error is not None:
            raise self.release_error
        if self.release_hang:
            await asyncio.Event().wait()
        return ReleaseNameReply.RELEASED

    def disconnect(self) -> None:
        super().disconnect()
        if self.disconnect_error is not None:
            raise self.disconnect_error


async def prepare_and_exit(bus: FakeBus) -> None:
    assert bus.interface is not None
    await call(bus.interface, "PrepareShutdown")
    await call(bus.interface, "Exit")


def test_exit_flush_timeout_is_bounded() -> None:
    assert service_cli._EXIT_FLUSH_TIMEOUT_S == 3.0  # pyright: ignore[reportPrivateUsage]


async def test_exit_defers_stop_until_loop_turn() -> None:
    events: list[str] = []
    bus = FlushBus(events)
    stopped = asyncio.Event()
    entered = asyncio.Event()
    task = await start_running(events, FakeService(events), bus, stopped, entered)
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert bus.interface is not None
        await call(bus.interface, "PrepareShutdown")
        await call(bus.interface, "Exit")
        assert not stopped.is_set()
        await asyncio.sleep(0)
        assert stopped.is_set()
        async with asyncio.timeout(2):
            await task
    finally:
        await join_task(task)
    assert events.count("disconnect") == 1


async def test_exit_flush_runs_after_cleanup_before_disconnect() -> None:
    events: list[str] = []
    bus = FlushBus(events)
    stopped = asyncio.Event()
    entered = asyncio.Event()
    task = await start_running(events, FakeService(events), bus, stopped, entered)
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        await prepare_and_exit(bus)
        async with asyncio.timeout(2):
            await task
    finally:
        await join_task(task)
    assert events.count(f"release:{BUS_NAME}") == 1
    assert events.count("disconnect") == 1
    assert events.index("service-stop") < events.index(f"release:{BUS_NAME}")
    assert events.index(f"release:{BUS_NAME}") < events.index("disconnect")


async def test_signal_stop_skips_flush_but_disconnects_once() -> None:
    events: list[str] = []
    bus = FlushBus(events)
    stopped = asyncio.Event()
    entered = asyncio.Event()
    task = await start_running(events, FakeService(events), bus, stopped, entered)
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        stopped.set()
        async with asyncio.timeout(2):
            await task
    finally:
        await join_task(task)
    assert not [item for item in events if item.startswith("release:")]
    assert events.count("disconnect") == 1


async def test_flush_failure_still_disconnects_once_without_error() -> None:
    events: list[str] = []
    bus = FlushBus(events)
    bus.release_error = RuntimeError("fake flush failure")
    stopped = asyncio.Event()
    entered = asyncio.Event()
    task = await start_running(events, FakeService(events), bus, stopped, entered)
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        await prepare_and_exit(bus)
        async with asyncio.timeout(2):
            await task
    finally:
        await join_task(task)
    assert events.count(f"release:{BUS_NAME}") == 1
    assert events.count("disconnect") == 1


async def test_disconnect_error_survives_flush_failure() -> None:
    events: list[str] = []
    bus = FlushBus(events)
    disconnect_failure = RuntimeError("fake disconnect failure")
    bus.release_error = RuntimeError("fake flush failure")
    bus.disconnect_error = disconnect_failure
    stopped = asyncio.Event()
    entered = asyncio.Event()
    task = await start_running(events, FakeService(events), bus, stopped, entered)
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        await prepare_and_exit(bus)
        with pytest.raises(RuntimeError) as raised:
            async with asyncio.timeout(2):
                await task
    finally:
        await join_task(task)
    assert raised.value is disconnect_failure
    assert events.count("disconnect") == 1


async def test_hanging_flush_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_cli, "_EXIT_FLUSH_TIMEOUT_S", 0.05)
    events: list[str] = []
    bus = FlushBus(events)
    bus.release_hang = True
    stopped = asyncio.Event()
    entered = asyncio.Event()
    task = await start_running(events, FakeService(events), bus, stopped, entered)
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        await prepare_and_exit(bus)
        async with asyncio.timeout(2):
            await task
    finally:
        await join_task(task)
    assert events.count("disconnect") == 1


async def test_bus_without_release_stays_compatible() -> None:
    events: list[str] = []
    bus = FakeBus(events)
    assert not hasattr(bus, "release_name")
    stopped = asyncio.Event()
    entered = asyncio.Event()
    task = await start_running(events, FakeService(events), bus, stopped, entered)
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert bus.interface is not None
        await call(bus.interface, "PrepareShutdown")
        assert events.count("service-stop") == 1
        await call(bus.interface, "Exit")
        async with asyncio.timeout(2):
            await task
    finally:
        await join_task(task)
    assert events.count("service-stop") == 1
    assert events.count("disconnect") == 1


async def test_cancelled_exit_cleanup_keeps_identity_and_disconnects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service_cli, "_EXIT_FLUSH_TIMEOUT_S", 0.5)
    events: list[str] = []
    bus = FlushBus(events)
    bus.release_hang = True
    stopped = asyncio.Event()
    entered = asyncio.Event()
    task = await start_running(events, FakeService(events), bus, stopped, entered)
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert bus.interface is not None
        await call(bus.interface, "PrepareShutdown")
        await call(bus.interface, "Exit")
        await asyncio.sleep(0)
        task.cancel("single fake exit cancellation")
        try:
            async with asyncio.timeout(2):
                await task
        except asyncio.CancelledError as observed:
            assert observed.args == ("single fake exit cancellation",)
        else:
            pytest.fail("exit cleanup cancellation must propagate")
    finally:
        bus.release_hang = False
        await join_task(task)
    assert events.count("disconnect") == 1


def _missing_isolation_tool() -> str | None:
    if shutil.which("dbus-run-session") is None:
        return "dbus-run-session is unavailable"
    if shutil.which("dbus-send") is None:
        return "dbus-send is unavailable"
    return None


def test_isolated_transport_exit_has_clean_stderr(tmp_path: Path) -> None:
    missing = _missing_isolation_tool()
    if missing is not None:
        pytest.skip(missing)
    out_dir = tmp_path / "exit-probe"
    out_dir.mkdir()
    (out_dir / "svc.py").write_text(
        textwrap.dedent(
            """\
            import asyncio
            import sys
            from pathlib import Path
            from naga_control.domain.hardware import HardwareState
            from naga_control.service.service_cli import run as run_service
            STOP_FILE = Path(sys.argv[1])
            class FakeLifecycle:
                def __init__(self) -> None:
                    self.stops = 0
                async def start(self) -> HardwareState:
                    return HardwareState("absent", 1)
                async def stop(self) -> None:
                    self.stops += 1
                    STOP_FILE.write_text("stop\\n" * self.stops)
                def snapshot(self) -> dict[str, object]:
                    return {"status": "available"}
                def release_all(self) -> None: ...
                def configuration_document(self) -> str:
                    return ""
                def configuration_revision(self) -> int:
                    return 0
                async def apply_configuration(self, e: int, d: str) -> int:
                    return 0
                async def select_profile(self, p: str) -> int:
                    return 0
                async def begin_calibration(self) -> bool:
                    return True
                async def end_calibration(self) -> bool:
                    return False
            async def main() -> None:
                await run_service(
                    FakeLifecycle(), topology_watcher=None, openrazer_lifecycle=None
                )
            asyncio.run(main())
            """
        )
    )
    helper = Path(__file__).resolve().parents[1] / "scripts" / "session_service.sh"
    assert helper.is_file()
    orchestrator = out_dir / "run.sh"
    orchestrator.write_text(
        textwrap.dedent(
            """\
            set -u
            OUT="$1"
            HELPER="$2"
            PYTHON="$3"
            "$PYTHON" "$OUT/svc.py" "$OUT/stops.txt" 2>"$OUT/svc-stderr.txt" &
            SVC_PID=$!
            READY=0
            for _ in $(seq 1 50); do
              if dbus-send --session --print-reply --reply-timeout=10000 \\
                  --dest=org.freedesktop.DBus /org/freedesktop/DBus \\
                  org.freedesktop.DBus.NameHasOwner \\
                  string:org.nagacontrol.Service1 2>/dev/null \\
                  | grep -q 'boolean true'; then
                READY=1
                break
              fi
              sleep 0.2
            done
            if [ "$READY" != "1" ]; then
              kill "$SVC_PID" 2>/dev/null || true
              wait "$SVC_PID" 2>/dev/null || true
              echo "READY=0"
              exit 10
            fi
            bash "$HELPER" stop >"$OUT/stop.txt" 2>&1
            STOP_RC=$?
            wait "$SVC_PID"
            SVC_RC=$?
            echo "STOP_RC=$STOP_RC SVC_RC=$SVC_RC READY=$READY"
            """
        )
    )
    completed = subprocess.run(
        [
            "dbus-run-session",
            "--",
            "bash",
            str(orchestrator),
            str(out_dir),
            str(helper),
            sys.executable,
        ],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=tmp_path,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert "READY=1" in completed.stdout
    assert "STOP_RC=0" in completed.stdout
    assert "SVC_RC=0" in completed.stdout
    assert (out_dir / "stop.txt").read_text() == "inactive\n"
    assert (out_dir / "stops.txt").read_text() == "stop\n"
    stderr_text = (out_dir / "svc-stderr.txt").read_text()
    assert "BrokenPipeError" not in stderr_text
    assert "never retrieved" not in stderr_text
