import argparse
import asyncio
import signal

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

    async def request_name(self, name: str) -> object:
        self.events.append(f"name:{name}")
        return object()

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


def test_parser_accepts_debug() -> None:
    assert build_parser().parse_args(["--debug"]) == argparse.Namespace(debug=True)


def test_run_stops_the_service_after_a_signal() -> None:
    asyncio.run(_exercise_run())


async def _exercise_run() -> None:
    service = Service()
    stopped = asyncio.Event()
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
    await asyncio.sleep(0)
    stopped.set()
    await task

    assert signals == [signal.SIGINT, signal.SIGTERM]
    assert service.events == ["start", "stop"]
    assert lifecycle.events == ["start", "stop"]
    assert bus.events == [
        "name:org.nagacontrol.Service1",
        "export:/org/nagacontrol/Service1",
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
