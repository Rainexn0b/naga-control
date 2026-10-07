import argparse
import asyncio
import signal
from typing import Literal

from dbus_next.constants import NameFlag, RequestNameReply

from naga_control.domain.hardware import HardwareState
from naga_control.service.service_cli import build_parser, run


class Service:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def start(self) -> HardwareState:
        self.events.append("start")
        return HardwareState("absent", 1)

    async def stop(self) -> None:
        self.events.append("stop")

    def snapshot(self) -> dict[str, object]:
        return {"status": "absent"}

    def release_all(self) -> None:
        self.events.append("release")

    def configuration_document(self) -> str:
        return ""

    def configuration_revision(self) -> int:
        return 0

    async def apply_configuration(self, expected_revision: int, document: str) -> int:
        return 0

    async def select_profile(self, profile_id: str) -> int:
        return 0

    async def begin_calibration(self) -> bool:
        return True

    async def end_calibration(self) -> bool:
        return False


class Bus:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def request_name(self, name: str, flags: NameFlag = NameFlag.NONE) -> object:
        assert flags == NameFlag.DO_NOT_QUEUE
        self.events.append(f"name:{name}")
        return RequestNameReply.PRIMARY_OWNER

    def export(self, path: str, interface: object) -> None:
        self.events.append(f"export:{path}")

    def disconnect(self) -> None:
        self.events.append("disconnect")


class Lifecycle:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def start(self) -> None:
        self.events.append("start")

    async def stop(self) -> None:
        self.events.append("stop")


class RunningStopEvent(asyncio.Event):
    def __init__(self) -> None:
        super().__init__()
        self.wait_entered = asyncio.Event()

    async def wait(self) -> Literal[True]:
        self.wait_entered.set()
        return await super().wait()


def test_parser_accepts_debug() -> None:
    assert build_parser().parse_args(["--debug"]) == argparse.Namespace(debug=True)


def test_run_stops_the_service_after_a_signal() -> None:
    asyncio.run(_exercise_run())


async def _exercise_run() -> None:
    service = Service()
    stopped = RunningStopEvent()
    signals: list[signal.Signals] = []
    bus = Bus()
    lifecycle = Lifecycle()

    task = asyncio.create_task(
        run(
            service,
            install_signal_handler=lambda handled, callback: signals.append(handled),
            stop_event=stopped,
            bus_factory=lambda: _bus(bus),
            openrazer_lifecycle=lifecycle,
        )
    )
    try:
        await asyncio.wait_for(stopped.wait_entered.wait(), timeout=2)
        stopped.set()
        await asyncio.wait_for(task, timeout=2)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=2)

    assert signals == [signal.SIGINT, signal.SIGTERM]
    assert service.events == ["start", "stop"]
    assert lifecycle.events == ["start", "stop"]
    assert bus.events == [
        "export:/org/nagacontrol/Service1",
        "name:org.nagacontrol.Service1",
        "disconnect",
    ]


async def _bus(bus: Bus) -> Bus:
    return bus


def test_module_entrypoint_prints_usage() -> None:
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "naga_control.service.service_cli", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "usage" in result.stdout.lower()
