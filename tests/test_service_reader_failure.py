"""Service reader-failure production wiring with real session stack."""

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import replace

import pytest
from reader_failure_fakes import make_connection
from service_runtime_fakes import Worker

from naga_control.adapters.evdev.discovery import EventNode, NagaConnection
from naga_control.application import service_factory as factory_module
from naga_control.application.service_factory import create_service
from naga_control.domain.actions import KeyAction
from naga_control.domain.defaults import default_configuration
from naga_control.domain.intents import KeyOutputIntent
from naga_control.domain.profiles import Binding, Configuration, as_logical_control
from naga_control.ports.forwarding import ForwardingProxySpec


class FakeKeyboard:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.intents: list[KeyOutputIntent] = []
        self.released_intents: list[KeyOutputIntent] = []
        self.held: set[str] = set()
        self.closed = False

    def emit(self, intent: KeyOutputIntent) -> None:
        self.events.append(f"keyboard.emit:{intent.key}:{intent.value}")
        self.intents.append(intent)
        if intent.value == 1:
            self.held.add(intent.key)
        elif intent.value == 0:
            self.held.discard(intent.key)

    def release_all(self) -> None:
        self.events.append("keyboard.release")
        for key in sorted(self.held):
            self.released_intents.append(KeyOutputIntent(key, 0))
        self.held.clear()

    def close(self) -> None:
        self.events.append("keyboard.close")
        self.closed = True


class FakeMouse:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.closed = False

    def emit(self, intent: object) -> None:
        return None

    def release_all(self) -> None:
        self.events.append("mouse.release")

    def close(self) -> None:
        self.events.append("mouse.close")


class FakeEvent:
    def __init__(self, event_type: int, code: int, value: int) -> None:
        self.type = event_type
        self.code = code
        self.value = value


class FakePreparedSource:
    def __init__(
        self,
        node: EventNode,
        mode: str,
        events: list[str],
        fault_gate: asyncio.Event,
    ) -> None:
        self.node = node
        self.mode = mode
        self.events = events
        self.fault_gate = fault_gate
        iface = node.interface_number
        self.forwarding_proxy_spec = ForwardingProxySpec(
            f"proxy-{iface}", f"phys-{iface}", 3, 1, 2, 3, (), {}
        )
        self.grabbed = False
        self.ungrabbed = False
        self.closed = False

    async def async_read_loop(self) -> AsyncIterator[FakeEvent]:
        if self.mode == "f17_hold":
            yield FakeEvent(4, 4, 458860)
            yield FakeEvent(1, 187, 1)
            yield FakeEvent(0, 0, 0)
            await asyncio.Event().wait()
            yield FakeEvent(0, 0, 0)
        elif self.mode == "fault":
            await self.fault_gate.wait()
            raise OSError(19, "no such device")
        else:
            await asyncio.Event().wait()
            yield FakeEvent(0, 0, 0)

    def active_keys(self) -> tuple[int, ...]:
        return ()

    def active_abs_values(self) -> dict[int, int]:
        return {}

    def revalidate(self) -> None:
        self.events.append(f"source.revalidate:{self.node.interface_number}")

    def drain_pending_frames(self) -> None:
        self.events.append(f"source.drain:{self.node.interface_number}")

    def grab(self) -> None:
        self.events.append(f"source.grab:{self.node.interface_number}")
        self.grabbed = True

    def ungrab(self) -> None:
        self.events.append(f"source.ungrab:{self.node.interface_number}")
        self.ungrabbed = True
        self.grabbed = False

    def close(self) -> None:
        self.events.append(f"source.close:{self.node.interface_number}")
        self.closed = True


class FakeProxy:
    def __init__(self, events: list[str], name: str) -> None:
        self.events = events
        self.name = name
        self.closed = False

    def write(self, event_type: int, code: int, value: int) -> None:
        return None

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.events.append(f"proxy.close:{self.name}")
        self.closed = True


class FakeProxyFactory:
    def __init__(self, events: list[str], proxies: list[FakeProxy]) -> None:
        self.events = events
        self.proxies = proxies

    def create(self, spec: ForwardingProxySpec) -> FakeProxy:
        self.events.append(f"proxy.create:{spec.name}")
        proxy = FakeProxy(self.events, spec.name)
        self.proxies.append(proxy)
        return proxy


class FakeWaiter:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def wait_ready(self, spec: ForwardingProxySpec) -> None:
        self.events.append(f"proxy.ready:{spec.name}")


def _right_ctrl_configuration() -> Configuration:
    base = default_configuration()
    profile = base.profile("default")
    rebound = replace(
        profile.bindings,
        common=(
            Binding(as_logical_control("dpi_up"), profile.bindings.common[0].action),
            Binding(as_logical_control("dpi_down"), profile.bindings.common[1].action),
            Binding(as_logical_control("ring_finger"), KeyAction("right_ctrl")),
        ),
    )
    rebound_profile = replace(profile, bindings=rebound)
    return replace(base, profiles=(("default", rebound_profile),), default_profile="default")


async def _wait_for(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    await asyncio.wait_for(_poll(predicate), timeout)


async def _poll(predicate: Callable[[], bool]) -> None:
    while not predicate():
        await asyncio.sleep(0.01)


def _fresh_connection() -> NagaConnection:
    return NagaConnection(
        "/sys/devices/fake-physical-usb-2",
        "1532",
        "00e8",
        "hyperspeed",
        None,
        None,
        tuple(
            EventNode(
                f"/dev/input/new-{interface}",
                "/sys/devices/fake-physical-usb-2",
                interface,
                "1532",
                "00e8",
            )
            for interface in ("00", "01", "02")
        ),
    )


async def test_explicit_topology_recovery_rebuilds_verified_grabs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    keyboards: list[FakeKeyboard] = []
    sources: list[FakePreparedSource] = []
    proxies: list[FakeProxy] = []
    fault_gate = asyncio.Event()
    worker = Worker()
    worker.events = events
    configuration = _right_ctrl_configuration()
    connection = make_connection()

    def make_keyboard() -> FakeKeyboard:
        keyboard = FakeKeyboard(events)
        keyboards.append(keyboard)
        return keyboard

    def open_source(node: EventNode) -> FakePreparedSource:
        if node.event_path.startswith("/dev/input/new-"):
            mode = "hang"
        elif node.interface_number == "00":
            mode = "fault"
        elif node.interface_number == "01":
            mode = "f17_hold"
        else:
            mode = "hang"
        source = FakePreparedSource(node, mode, events, fault_gate)
        sources.append(source)
        return source

    monkeypatch.setattr(factory_module, "create_virtual_keyboard", make_keyboard)
    monkeypatch.setattr(factory_module, "create_virtual_mouse", lambda: FakeMouse(events))
    monkeypatch.setattr(factory_module, "open_evdev_source", open_source)
    monkeypatch.setattr(
        factory_module, "UInputForwardingProxyFactory", lambda: FakeProxyFactory(events, proxies)
    )
    monkeypatch.setattr(factory_module, "create_proxy_readiness_waiter", lambda: FakeWaiter(events))
    service = create_service(
        discover=lambda: (connection,),
        load_configuration=lambda: configuration,
        worker=worker,  # type: ignore[arg-type]
    )
    try:
        await asyncio.wait_for(service.start(), 2)
        assert service.snapshot()["mode_ready"] is True
        old_session = service._sessions.current  # pyright: ignore[reportPrivateUsage]
        assert old_session is not None
        await _wait_for(lambda: any(k.intents for k in keyboards))
        assert KeyOutputIntent("right_ctrl", 1) in keyboards[0].intents
        assert "right_ctrl" in keyboards[0].held
        fault_gate.set()
        await _wait_for(lambda: keyboards[0].released_intents != [])
        assert KeyOutputIntent("right_ctrl", 0) in keyboards[0].released_intents
        assert keyboards[0].held == set()
        await _wait_for(lambda: service.snapshot()["mode_ready"] is False)
        assert "recovery pending" in str(service.snapshot()["mode_error"])
        await _wait_for(lambda: all(s.ungrabbed and s.closed for s in sources[:3]))
        for source in sources[:3]:
            assert source.ungrabbed and source.closed
        for proxy in proxies[:3]:
            assert proxy.closed
        assert "stale" in events
        fence_count = events.count("stale")
        fail_index = events.index("stale")
        assert any(
            "source.ungrab:00" in e or "source.close:00" in e for e in events[: fail_index + 5]
        )

        def _after(token: str, after: int) -> int:
            return next(i for i, e in enumerate(events) if e == token and i > after)

        # Failing 00 cleanup precedes the fence; siblings follow it.
        assert events.index("source.close:00") < fail_index
        assert _after("source.ungrab:01", fail_index) < len(events)
        assert _after("source.close:01", fail_index) < len(events)
        stale_before = events.count("stale")
        service.record_input_failure(old_session)  # type: ignore[arg-type]
        service.record_input_failure(old_session)  # type: ignore[arg-type]
        assert events.count("stale") == stale_before
        assert fence_count == stale_before
        fresh = _fresh_connection()
        old_source_count = len(sources)
        old_proxy_count = len(proxies)
        state = await asyncio.wait_for(service.apply_topology((fresh,)), 2)
        assert state.status == "available"
        assert service.snapshot()["mode_ready"] is True
        assert len(sources) == old_source_count + 3
        assert len(proxies) == old_proxy_count + 3
        new_sources = sources[old_source_count:]
        assert all(s.grabbed for s in new_sources)
        assert all(not s.closed for s in new_sources)
        for proxy in proxies[old_proxy_count:]:
            assert not proxy.closed
        read_after = _after("read_mode", fail_index)
        ready_after = _after("proxy.ready:proxy-01", read_after)
        grab_after = _after("source.grab:01", ready_after)
        assert read_after > fail_index
        assert ready_after > read_after
        assert grab_after > ready_after
        old_done = max(
            events.index("source.close:00"),
            _after("source.close:01", fail_index),
            _after("source.close:02", fail_index),
        )
        assert old_done < grab_after
        new_session = service._sessions.current  # pyright: ignore[reportPrivateUsage]
        assert new_session is not None and new_session is not old_session
        stale_after_recovery = events.count("stale")
        service.record_input_failure(old_session)  # type: ignore[arg-type]
        assert events.count("stale") == stale_after_recovery
        service.record_input_failure(new_session)  # type: ignore[arg-type]
        after_first = events.count("stale")
        service.record_input_failure(new_session)  # type: ignore[arg-type]
        assert events.count("stale") == after_first
    finally:
        fault_gate.set()
        await asyncio.gather(service.stop(), return_exceptions=True)


async def test_poll_recovers_automatically_on_updated_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    keyboards: list[FakeKeyboard] = []
    sources: list[FakePreparedSource] = []
    proxies: list[FakeProxy] = []
    fault_gate = asyncio.Event()
    worker = Worker()
    worker.events = events
    configuration = _right_ctrl_configuration()
    current: list[NagaConnection] = [make_connection()]

    def make_keyboard() -> FakeKeyboard:
        keyboard = FakeKeyboard(events)
        keyboards.append(keyboard)
        return keyboard

    def open_source(node: EventNode) -> FakePreparedSource:
        if node.event_path.startswith("/dev/input/new-"):
            mode = "hang"
        elif node.interface_number == "00":
            mode = "fault"
        elif node.interface_number == "01":
            mode = "f17_hold"
        else:
            mode = "hang"
        source = FakePreparedSource(node, mode, events, fault_gate)
        sources.append(source)
        return source

    monkeypatch.setattr(factory_module, "create_virtual_keyboard", make_keyboard)
    monkeypatch.setattr(factory_module, "create_virtual_mouse", lambda: FakeMouse(events))
    monkeypatch.setattr(factory_module, "open_evdev_source", open_source)
    monkeypatch.setattr(
        factory_module, "UInputForwardingProxyFactory", lambda: FakeProxyFactory(events, proxies)
    )
    monkeypatch.setattr(factory_module, "create_proxy_readiness_waiter", lambda: FakeWaiter(events))
    service = create_service(
        discover=lambda: (current[0],),
        load_configuration=lambda: configuration,
        worker=worker,  # type: ignore[arg-type]
    )
    service._state_poll_interval = 0.02  # pyright: ignore[reportPrivateUsage]
    try:
        await asyncio.wait_for(service.start(), 2)
        await _wait_for(lambda: any(k.intents for k in keyboards))
        fault_gate.set()
        await _wait_for(lambda: service.snapshot()["mode_ready"] is False)
        current[0] = _fresh_connection()
        await _wait_for(lambda: service.snapshot()["mode_ready"] is True, timeout=3.0)
        assert len(sources) >= 6
        assert service.snapshot()["mode_ready"] is True
    finally:
        fault_gate.set()
        await asyncio.gather(service.stop(), return_exceptions=True)
