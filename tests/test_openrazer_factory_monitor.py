"""DEBT-15 monitor integration through the real default factory, fakes only."""

from __future__ import annotations

import asyncio
from types import ModuleType, SimpleNamespace

import pytest

from naga_control.adapters.openrazer import lifecycle_monitor
from naga_control.adapters.openrazer.lifecycle_monitor import (
    DEVICE_ADDED_RULE,
    DEVICE_REMOVED_RULE,
    NAME_OWNER_CHANGED_RULE,
    OpenRazerLifecycleMonitor,
)
from naga_control.domain.hardware import HardwareState
from naga_control.ports.hardware import NagaTopology

EXPECTED_RULES = (DEVICE_ADDED_RULE, DEVICE_REMOVED_RULE, NAME_OWNER_CHANGED_RULE)


class _Provider:
    def __init__(self) -> None:
        self.calls = 0

    def get_topology(self) -> tuple[NagaTopology, ...]:
        self.calls += 1
        return ()


class _Controller:
    def __init__(self) -> None:
        self.stale_marks = 0
        self.rescans = 0
        self.rescan_done = asyncio.Event()

    def mark_topology_stale(self) -> None:
        self.stale_marks += 1

    async def rescan(self, connections: tuple[NagaTopology, ...]) -> HardwareState:
        self.rescans += 1
        self.rescan_done.set()
        return HardwareState(status="absent", generation=self.rescans)


async def test_real_factory_failure_then_retry_subscribes_and_rescans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = object()
    events: list[str] = []
    primary = OSError("fake raw connect failure")
    state: dict[str, int] = {"connects": 0}
    raws: list[FakeBus] = []
    message_calls: list[tuple[str, tuple[str, ...]]] = []

    class FakeBus:
        def __init__(self, *, bus_type: object) -> None:
            assert bus_type is session
            events.append("construct")
            self.handlers: list[object] = []
            self.calls: list[object] = []
            self.disconnects = 0
            raws.append(self)

        async def connect(self) -> FakeBus:
            events.append("connect")
            state["connects"] += 1
            if state["connects"] == 1:
                raise primary
            return self

        def disconnect(self) -> None:
            events.append("disconnect")
            self.disconnects += 1

        async def call(self, message: object) -> object:
            self.calls.append(message)
            return SimpleNamespace()

        def add_message_handler(self, handler: object) -> None:
            self.handlers.append(handler)

        def remove_message_handler(self, handler: object) -> None:
            if handler in self.handlers:
                self.handlers.remove(handler)

    def fake_message(
        *,
        destination: object,
        path: object,
        interface: object,
        member: str,
        signature: object,
        body: list[str],
    ) -> object:
        message_calls.append((member, tuple(body)))
        return SimpleNamespace(member=member, body=list(body))

    aio = ModuleType("dbus_next.aio")
    aio.MessageBus = FakeBus  # type: ignore[attr-defined]
    dbus_module = ModuleType("dbus_next")
    bus_type_module = ModuleType("FakeBusType")
    bus_type_module.SESSION = session  # type: ignore[attr-defined]
    dbus_module.BusType = bus_type_module  # type: ignore[attr-defined]
    dbus_module.Message = fake_message  # type: ignore[attr-defined]

    def fake_import(name: str) -> ModuleType:
        events.append(f"import:{name}")
        return {"dbus_next.aio": aio, "dbus_next": dbus_module}[name]

    monkeypatch.setattr(lifecycle_monitor, "import_module", fake_import)

    provider = _Provider()
    controller = _Controller()
    monitor = OpenRazerLifecycleMonitor(
        provider,
        controller,
        bus_factory=lifecycle_monitor._default_bus_factory,  # pyright: ignore[reportPrivateUsage]
        debounce_seconds=0,
    )
    with pytest.raises(OSError) as raised:
        async with asyncio.timeout(2):
            await monitor.start()
    assert raised.value is primary
    assert len(raws) == 1
    assert raws[0].disconnects == 1
    assert raws[0].handlers == []
    assert raws[0].calls == []
    assert message_calls == []
    assert provider.calls == 0
    assert controller.stale_marks == 0
    assert controller.rescans == 0

    async with asyncio.timeout(2):
        await monitor.start()
    assert len(raws) == 2
    assert raws[1].disconnects == 0
    await asyncio.wait_for(controller.rescan_done.wait(), timeout=2)
    assert provider.calls == 1
    assert controller.stale_marks == 1
    assert controller.rescans == 1
    assert len(raws[1].handlers) == 1
    assert [call[0] for call in message_calls] == ["AddMatch"] * 3
    assert [call[1][0] for call in message_calls] == list(EXPECTED_RULES)

    async with asyncio.timeout(2):
        await monitor.stop()
    assert raws[1].handlers == []
    assert raws[1].disconnects == 1
    assert [call[0] for call in message_calls].count("RemoveMatch") == 3
