"""User-service entry point for the first hardware/remapping slice."""

import argparse
import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable, Coroutine
from contextlib import suppress
from typing import Protocol

from naga_control.adapters.evdev.discovery import discover_naga_connections
from naga_control.adapters.openrazer.lifecycle_monitor import OpenRazerLifecycleMonitor
from naga_control.application.service_factory import create_service
from naga_control.domain.hardware import HardwareState
from naga_control.ipc.server import SessionBus, connect_session_bus, publish_service
from naga_control.ipc.service import NagaControlInterface
from naga_control.ports.hardware import NagaTopology
from naga_control.service.hotplug import create_udev_topology_watcher


class ServiceLifecycle(Protocol):
    async def start(self) -> HardwareState: ...

    async def stop(self) -> None: ...

    def snapshot(self) -> dict[str, object]: ...

    def release_all(self) -> None: ...

    def configuration_document(self) -> str: ...

    def configuration_revision(self) -> int: ...

    async def apply_configuration(self, expected_revision: int, document: str) -> int: ...

    async def select_profile(self, profile_id: str) -> int: ...

    async def begin_calibration(self) -> bool: ...

    async def end_calibration(self) -> bool: ...


class AuxiliaryLifecycle(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class _PhysicalTopology:
    def get_topology(self) -> tuple[NagaTopology, ...]:
        return discover_naga_connections()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="naga-control-service")
    parser.add_argument("--debug", action="store_true", help="enable debug logging")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)
    service = create_service()
    openrazer_lifecycle = OpenRazerLifecycleMonitor(_PhysicalTopology(), service)
    try:
        asyncio.run(
            run(
                service,
                topology_watcher=create_udev_topology_watcher(service, discover_naga_connections),
                openrazer_lifecycle=openrazer_lifecycle,
            )
        )
    except KeyboardInterrupt:
        return 130
    except Exception:
        logging.getLogger(__name__).exception("Naga Control service stopped during startup")
        return 1
    return 0


async def run(
    service: ServiceLifecycle,
    *,
    install_signal_handler: Callable[[signal.Signals, Callable[[], None]], None] | None = None,
    stop_event: asyncio.Event | None = None,
    bus_factory: Callable[[], Awaitable[SessionBus]] = connect_session_bus,
    topology_watcher: Callable[[], Coroutine[None, None, None]] | None = None,
    openrazer_lifecycle: AuxiliaryLifecycle | None = None,
) -> None:
    """Run until SIGINT/SIGTERM and always release outputs through service shutdown."""
    stopped = stop_event or asyncio.Event()
    install = install_signal_handler or asyncio.get_running_loop().add_signal_handler
    for handled_signal in (signal.SIGINT, signal.SIGTERM):
        install(handled_signal, stopped.set)
    bus: SessionBus | None = None
    watcher: asyncio.Task[None] | None = None
    lifecycle_started = False
    try:
        state = await service.start()
        if openrazer_lifecycle is not None:
            await openrazer_lifecycle.start()
            lifecycle_started = True
        bus = await bus_factory()
        await publish_service(bus, NagaControlInterface(service))
        if topology_watcher is not None:
            watcher = asyncio.create_task(topology_watcher())
        logging.getLogger(__name__).info("Naga Control service state: %s", state.status)
        await stopped.wait()
    finally:
        if watcher is not None:
            watcher.cancel()
            with suppress(asyncio.CancelledError):
                await watcher
        if lifecycle_started and openrazer_lifecycle is not None:
            await openrazer_lifecycle.stop()
        await service.stop()
        if bus is not None:
            bus.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
