import asyncio
import logging
from typing import ClassVar

import pytest

from naga_control.adapters.evdev.discovery import NagaConnection
from naga_control.adapters.evdev.monitor import AsyncioReaderLoop
from naga_control.domain.hardware import HardwareState
from naga_control.service.hotplug import create_udev_topology_watcher, supervise_topology


class Applier:
    def __init__(self) -> None:
        self.applied: list[int] = []

    async def apply_topology(self, connections: tuple[NagaConnection, ...]) -> HardwareState:
        self.applied.append(len(connections))
        return HardwareState("unavailable", 1)


class FailingApplier:
    calls: ClassVar[list[int]] = []

    async def apply_topology(self, connections: tuple[NagaConnection, ...]) -> HardwareState:
        FailingApplier.calls.append(len(connections))
        raise RuntimeError("session rebuild failed")


class Changes:
    def __init__(self, snapshots: list[tuple[NagaConnection, ...]]) -> None:
        self._snapshots = list(snapshots)
        self.started = False
        self.closed = False
        self._done = asyncio.Event()

    def start(self, loop: AsyncioReaderLoop) -> tuple[NagaConnection, ...]:
        self.started = True
        return ()

    async def next_change(self) -> tuple[NagaConnection, ...] | None:
        if self._snapshots:
            return self._snapshots.pop(0)
        self._done.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    def close(self) -> None:
        self.closed = True

    async def drained(self) -> None:
        await self._done.wait()


def test_supervisor_applies_each_change_and_closes_the_source() -> None:
    asyncio.run(_exercise_supervisor())


async def _exercise_supervisor() -> None:
    applier = Applier()
    changes = Changes([(_connection(),), ()])
    task = asyncio.create_task(supervise_topology(applier, changes))
    await changes.drained()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert changes.started
    assert applier.applied == [1, 0]
    assert changes.closed


def test_supervisor_survives_a_failing_apply(caplog: pytest.LogCaptureFixture) -> None:
    asyncio.run(_exercise_failed_apply(caplog))


async def _exercise_failed_apply(caplog: pytest.LogCaptureFixture) -> None:
    connections = (_connection(),)
    changes = Changes([connections, connections])
    with caplog.at_level(logging.ERROR):
        task = asyncio.create_task(supervise_topology(FailingApplier(), changes))
        await changes.drained()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert FailingApplier.calls == [1, 1]
    assert "could not be applied" in caplog.text
    assert changes.closed


def _connection() -> NagaConnection:
    return NagaConnection("/sys/usb", "1532", "00e8", "hyperspeed", None, None, ())


def test_watcher_factory_applies_changes_from_the_injected_source() -> None:
    asyncio.run(_exercise_watcher_factory())


async def _exercise_watcher_factory() -> None:
    applier = Applier()
    changes = Changes([(_connection(),), ()])
    watcher = create_udev_topology_watcher(applier, lambda: (), changes_factory=lambda: changes)
    task = asyncio.create_task(watcher())
    await changes.drained()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert changes.started
    assert applier.applied == [1, 0]
    assert changes.closed


async def test_supervisor_ignores_unchanged_topology_snapshots() -> None:
    applier = Applier()
    connection = (_connection(),)
    changes = Changes([connection, connection, ()])
    task = asyncio.create_task(supervise_topology(applier, changes))
    await changes.drained()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert applier.applied == [1, 0]
