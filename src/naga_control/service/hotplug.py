"""Supervise input-topology changes and rebuild the remapping session."""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Protocol

from naga_control.adapters.evdev.discovery import NagaConnection
from naga_control.adapters.evdev.monitor import AsyncioReaderLoop
from naga_control.domain.hardware import HardwareState

logger = logging.getLogger(__name__)


class TopologyApplier(Protocol):
    async def apply_topology(self, connections: tuple[NagaConnection, ...]) -> HardwareState: ...


class TopologyChangeSource(Protocol):
    def start(self, loop: AsyncioReaderLoop) -> tuple[NagaConnection, ...]: ...

    async def next_change(self) -> tuple[NagaConnection, ...] | None: ...

    def close(self) -> None: ...


type TopologyWatcher = Callable[[], Coroutine[None, None, None]]
type ChangeSourceFactory = Callable[[], TopologyChangeSource]


async def supervise_topology(service: TopologyApplier, changes: TopologyChangeSource) -> None:
    """Apply debounced topology changes until the supervisor is cancelled."""
    active = changes.start(asyncio.get_running_loop())
    try:
        while (connections := await changes.next_change()) is not None:
            if connections == active:
                continue
            try:
                state = await service.apply_topology(connections)
                logger.info("Naga Control topology applied: %s", state.status)
            except Exception:
                logger.exception("topology change could not be applied")
            else:
                active = connections
    finally:
        changes.close()


def create_udev_topology_watcher(
    service: TopologyApplier,
    discover: Callable[[], tuple[NagaConnection, ...]],
    *,
    changes_factory: ChangeSourceFactory | None = None,
) -> TopologyWatcher:
    """Build the default CLI watcher from the pyudev input monitor."""
    factory = changes_factory or _udev_changes_factory(discover)

    async def watch() -> None:
        await supervise_topology(service, factory())

    return watch


def _udev_changes_factory(
    discover: Callable[[], tuple[NagaConnection, ...]],
) -> ChangeSourceFactory:
    def create() -> TopologyChangeSource:
        from importlib import import_module
        from typing import cast

        from naga_control.adapters.evdev.discovery import UdevContext
        from naga_control.adapters.evdev.monitor import NagaDiscoveryMonitor, create_input_monitor

        context_factory = cast(Callable[[], UdevContext], import_module("pyudev").Context)
        return NagaDiscoveryMonitor(create_input_monitor(context_factory()), discover)

    return create
