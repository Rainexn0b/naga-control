"""Debounced input hotplug monitoring for physically discovered Naga nodes."""

import asyncio
from collections.abc import Callable
from importlib import import_module
from typing import Protocol, cast

from naga_control.adapters.evdev.discovery import NagaConnection, UdevContext


class UdevMonitor(Protocol):
    def fileno(self) -> int: ...

    def filter_by(self, subsystem: str) -> None: ...

    def start(self) -> None: ...

    def poll(self, timeout: float = 0) -> object | None: ...


class AsyncioReaderLoop(Protocol):
    def add_reader(self, fd: int, callback: Callable[[], None]) -> None: ...

    def remove_reader(self, fd: int) -> bool: ...


class _MonitorClass(Protocol):
    def from_netlink(self, context: UdevContext) -> UdevMonitor: ...


def create_input_monitor(context: UdevContext) -> UdevMonitor:
    """Create a pyudev monitor that observes input-interface changes only."""
    module = import_module("pyudev")
    monitor_class = cast(_MonitorClass, module.Monitor)
    monitor = monitor_class.from_netlink(context)
    monitor.filter_by("input")
    return monitor


class NagaDiscoveryMonitor:
    """Coalesce input udev changes after monitoring begins before enumeration."""

    def __init__(
        self,
        monitor: UdevMonitor,
        discover: Callable[[], tuple[NagaConnection, ...]],
        *,
        debounce_seconds: float = 0.1,
    ) -> None:
        if debounce_seconds < 0:
            raise ValueError("debounce_seconds must not be negative")
        self._monitor = monitor
        self._discover = discover
        self._debounce_seconds = debounce_seconds
        self._changed = asyncio.Event()
        self._loop: AsyncioReaderLoop | None = None
        self._closed = False

    def start(self, loop: AsyncioReaderLoop) -> tuple[NagaConnection, ...]:
        """Begin receiving udev events before taking the initial topology snapshot."""
        if self._loop is not None or self._closed:
            raise RuntimeError("discovery monitor is already running")
        self._monitor.start()
        loop.add_reader(self._monitor.fileno(), self._on_monitor_ready)
        self._loop = loop
        return self._discover()

    async def next_change(self) -> tuple[NagaConnection, ...] | None:
        """Return a snapshot after one or more debounced udev changes."""
        await self._changed.wait()
        while True:
            if self._closed:
                return None
            self._changed.clear()
            await asyncio.sleep(self._debounce_seconds)
            if self._closed:
                return None
            if not self._changed.is_set():
                return self._discover()

    def close(self) -> None:
        """Stop watching the monitor file descriptor without closing caller-owned udev state."""
        if self._loop is not None:
            self._loop.remove_reader(self._monitor.fileno())
            self._loop = None
        self._closed = True
        self._changed.set()

    def _on_monitor_ready(self) -> None:
        changed = False
        while self._monitor.poll(timeout=0) is not None:
            changed = True
        if changed:
            self._changed.set()
