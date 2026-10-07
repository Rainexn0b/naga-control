"""Discovery failures and recovery use injected snapshots, not hardware owners."""

from collections.abc import Iterable
from dataclasses import replace

import pytest
from test_openrazer_backend import FakeDevice, FakeManager

from naga_control.adapters.evdev.discovery import EventNode, NagaConnection, Transport
from naga_control.adapters.openrazer.backend import OpenRazerBackend
from naga_control.domain.defaults import default_configuration
from naga_control.domain.hardware import (
    DeviceModeError,
    HardwareIssueCode,
    HardwareState,
    HardwareStatus,
    HardwareTransport,
)


class SnapshotFactory:
    def __init__(self, *snapshots: FakeManager | Exception) -> None:
        self.snapshots = snapshots
        self.calls = 0

    def __call__(self) -> FakeManager:
        self.calls += 1
        snapshot = self.snapshots[self.calls - 1]
        if isinstance(snapshot, Exception):
            raise snapshot
        return snapshot


class BrokenEnumeration(FakeManager):
    def __init__(self, phase: str) -> None:
        super().__init__((FakeDevice(),))
        self.phase = phase
        self.visited = 0

    @property
    def devices(self) -> Iterable[object]:
        if self.phase == "property":
            raise RuntimeError("fake daemon is absent")
        return self._enumerate()

    def _enumerate(self) -> Iterable[object]:
        for device in super().devices:
            self.visited += 1
            yield device
        raise RuntimeError("fake daemon disappeared during enumeration")


class GuardedDevice(FakeDevice):
    def __init__(self) -> None:
        super().__init__()
        self.guarded = False
        self.hardware_accesses: list[tuple[str, str]] = []

    def __getattribute__(self, name: str) -> object:
        if name not in {"guarded", "hardware_accesses"} and object.__getattribute__(
            self, "__dict__"
        ).get("guarded", False):
            object.__getattribute__(self, "hardware_accesses").append(("read", name))
        return super().__getattribute__(name)

    def __setattr__(self, name: str, value: object) -> None:
        if name not in {"guarded", "hardware_accesses"} and object.__getattribute__(
            self, "__dict__"
        ).get("guarded", False):
            object.__getattribute__(self, "hardware_accesses").append(("write", name))
        super().__setattr__(name, value)

    @property
    def _dbus(self) -> object:
        # Mode lookup uses object.__getattribute__, which still invokes descriptors.
        if self.guarded:
            self.hardware_accesses.append(("read", "_dbus"))
        raise AttributeError("fake has no D-Bus object")


def test_guard_detects_same_value_write_nested_lighting_and_direct_mode_lookup() -> None:
    device = GuardedDevice()
    device.guarded = True
    device.poll_rate = 1000
    device.fx.misc.logo.brightness = 100.0
    with pytest.raises(AttributeError):
        object.__getattribute__(device, "_dbus")
    assert device.hardware_accesses == [
        ("write", "poll_rate"),
        ("read", "fx"),
        ("read", "_dbus"),
    ]


def assert_cleared(
    state: HardwareState,
    status: HardwareStatus,
    code: HardwareIssueCode,
    generation: int,
    transport: HardwareTransport | None = None,
) -> None:
    assert state.error is not None
    assert state.error.code == code
    assert state.error.message
    assert state == HardwareState(
        status=status, generation=generation, transport=transport, error=state.error
    )


def topology(transport: Transport, path: str = "/usb/fake") -> NagaConnection:
    product = "00e7" if transport == "wired" else "00e8"
    return NagaConnection(
        usb_path=path,
        vendor_id="1532",
        product_id=product,
        transport=transport,
        serial="test-only",
        physical_path="test-only",
        nodes=(EventNode("/not-a-device", path, "00", "1532", product),),
    )


@pytest.mark.parametrize("phase", ["construction", "property", "iteration"])
@pytest.mark.parametrize("previous_client", [False, True])
def test_daemon_failure_clears_state_and_later_action_reacquires(
    phase: str,
    previous_client: bool,
) -> None:
    old, awake, wrong_transport = FakeDevice(), FakeDevice(), FakeDevice(product_id=0x00E8)
    broken = BrokenEnumeration(phase)
    prior = [FakeManager((old,))] if previous_client else []
    factory = SnapshotFactory(
        *prior,
        RuntimeError("fake daemon is absent") if phase == "construction" else broken,
        FakeManager((wrong_transport, awake)),
    )
    backend = OpenRazerBackend(factory)
    if previous_client:
        assert backend.rescan((topology("wired"),)).status == "available"
    else:
        assert backend.state == HardwareState(status="absent", generation=0)

    failed = backend.rescan((topology("wired"),))

    assert backend.state is failed
    generation = 2 if previous_client else 1
    assert_cleared(failed, "unavailable", "backend_unavailable", generation, "wired")
    assert factory.calls == generation
    assert broken.visited == (1 if phase == "iteration" else 0)
    recovered = backend.set_scroll_mode("free_spin")
    assert backend.state is recovered
    assert recovered.status == "available" and recovered.generation == generation + 1
    assert recovered.transport == "wired" and recovered.scroll_mode == "free_spin"
    assert factory.calls == generation + 1
    assert old.stage_writes == old.scroll_writes == []
    assert wrong_transport.stage_writes == wrong_transport.scroll_writes == []
    assert awake.stage_writes == [] and awake.scroll_writes == [1]


@pytest.mark.parametrize(
    ("field", "reply", "code"),
    [
        ("dpi", (800,), "invalid_response"),
        ("dpi_stages", (True, ((800, 900),)), "invalid_response"),
        ("max_dpi", 50001, "invalid_response"),
        ("scroll_mode_options", ("tactile", "tactile"), "invalid_response"),
        ("scroll_acceleration", 1, "invalid_response"),
        ("scroll_smart_reel", AttributeError(), "unsupported_capability"),
        ("scroll_mode_options", RuntimeError(), "device_unavailable"),
    ],
)
def test_required_reply_failure_replaces_prior_observation_and_blocks_stale_writes(
    field: str, reply: object, code: HardwareIssueCode
) -> None:
    old, awake = FakeDevice(), FakeDevice()
    if isinstance(reply, AttributeError):
        broken = FakeDevice(missing=field)
    elif isinstance(reply, RuntimeError):
        broken = FakeDevice(failing=field)
    else:
        broken = FakeDevice()
        attribute = field if field == "max_dpi" else f"_{field}"
        setattr(broken, attribute, reply)
    factory = SnapshotFactory(FakeManager((old,)), FakeManager((broken,)), FakeManager((awake,)))
    backend = OpenRazerBackend(factory)
    assert backend.rescan((topology("wired"),)).status == "available"

    failed = backend.rescan((topology("wired"),))

    assert backend.state is failed
    unavailable = code == "device_unavailable"
    assert_cleared(
        failed,
        "unavailable" if unavailable else "unsupported",
        code,
        2,
        "wired" if unavailable else None,
    )
    after_action = backend.move_dpi_stage(1)
    if unavailable:
        assert after_action.status == "available" and after_action.generation == 3
        assert after_action.active_dpi_stage == 3 and factory.calls == 3
        assert awake.stage_writes == [(3, ((400, 500), (800, 900), (1200, 1300)))]
    else:
        assert after_action is failed and factory.calls == 2
        assert awake.stage_writes == []
    assert old.stage_writes == broken.stage_writes == []
    assert old.scroll_writes == broken.scroll_writes == awake.scroll_writes == []


def test_rescan_replaces_stale_object_even_when_transport_and_topology_are_unchanged() -> None:
    old = FakeDevice(dpi_stages=(1, ((400, 500), (800, 900))))
    fresh = FakeDevice(dpi_stages=(2, ((700, 750), (1400, 1450), (2800, 2850))))
    decoy = FakeDevice(product_id=0x00E8)
    factory = SnapshotFactory(FakeManager((old,)), FakeManager((decoy, fresh)))
    backend = OpenRazerBackend(factory)
    first = backend.rescan((topology("wired"),))
    second = backend.rescan((topology("wired"),))

    state = backend.move_dpi_stage(1)

    assert first.active_dpi_stage == 1 and first.generation == 1
    assert second.active_dpi_stage == 2 and second.generation == 2
    assert state is backend.state and state.status == "available" and state.generation == 2
    assert state.active_dpi_stage == 3 and factory.calls == 2
    assert fresh.stage_writes == [(3, ((700, 750), (1400, 1450), (2800, 2850)))]
    assert old.stage_writes == decoy.stage_writes == []
    assert old.scroll_writes == decoy.scroll_writes == fresh.scroll_writes == []


@pytest.mark.parametrize("selection", ["missing", "ambiguous"])
def test_missing_or_ambiguous_matching_clients_cannot_fall_back_to_old_client(
    selection: str,
) -> None:
    old = FakeDevice()
    candidates = (
        (object(), FakeDevice(vendor_id=True), FakeDevice(product_id=0x00E8))
        if selection == "missing"
        else (FakeDevice(), FakeDevice())
    )
    factory = SnapshotFactory(FakeManager((old,)), FakeManager(candidates))
    backend = OpenRazerBackend(factory)
    assert backend.rescan((topology("wired"),)).status == "available"

    state = backend.rescan((topology("wired"),))

    assert_cleared(
        state,
        "unsupported",
        "matching_device_not_found" if selection == "missing" else "ambiguous_matching_device",
        2,
    )
    assert backend.refresh_state() is state
    assert backend.move_dpi_stage(1) is state
    assert backend.set_scroll_mode("free_spin") is state
    assert factory.calls == 2 and old.stage_writes == old.scroll_writes == []
    for candidate in candidates:
        if isinstance(candidate, FakeDevice):
            assert candidate.stage_writes == candidate.scroll_writes == []


@pytest.mark.parametrize("second_transport", ["wired", "hyperspeed"])
def test_physical_topology_conflicts_fence_every_write_api_after_a_valid_selection(
    second_transport: Transport,
) -> None:
    device = GuardedDevice()
    factory = SnapshotFactory(FakeManager((device,)))
    backend = OpenRazerBackend(factory)
    first = topology("wired", "/usb/fake-first")
    second = topology(second_transport, "/usb/fake-second")
    assert first.usb_path != second.usb_path
    assert backend.rescan((first,)).status == "available"

    state = backend.rescan((first, second))
    device.guarded = True

    code = "transport_conflict" if second_transport == "hyperspeed" else "multiple_device_conflict"
    assert_cleared(state, code, code, 2)
    assert backend.move_dpi_stage(1) is state
    assert backend.move_scroll_mode(1) is state
    assert backend.set_scroll_mode("free_spin") is state
    applied, failures = backend.apply_profile_settings(default_configuration().profile("default"))
    assert applied is state and [failure.setting for failure in failures] == ["profile"]
    with pytest.raises(DeviceModeError) as error:
        backend.set_device_mode("software")
    assert error.value.code == "unavailable"
    assert backend.refresh_state() is state and factory.calls == 1
    assert device.hardware_accesses == []


def test_disappearance_clears_topology_and_prevents_action_reacquisition() -> None:
    device = FakeDevice()
    factory = SnapshotFactory(FakeManager((device,)))
    backend = OpenRazerBackend(factory)
    assert backend.rescan((topology("wired"),)).status == "available"

    state = backend.rescan(())

    assert state is backend.state and state == HardwareState(status="absent", generation=2)
    assert backend.refresh_state() is state
    assert backend.move_dpi_stage(1) is state
    assert backend.move_scroll_mode(1) is state
    assert factory.calls == 1 and device.stage_writes == device.scroll_writes == []


@pytest.mark.parametrize(("vendor", "product"), [("1234", "00e7"), ("1532", "00e8")])
def test_unsupported_physical_ids_cannot_reuse_a_previously_valid_selection(
    vendor: str,
    product: str,
) -> None:
    device = FakeDevice()
    factory = SnapshotFactory(FakeManager((device,)))
    backend = OpenRazerBackend(factory)
    connection = topology("wired")
    assert backend.rescan((connection,)).status == "available"
    unsupported = replace(
        connection,
        vendor_id=vendor,
        product_id=product,
        nodes=tuple(
            replace(node, vendor_id=vendor, product_id=product) for node in connection.nodes
        ),
    )

    state = backend.rescan((unsupported,))

    assert state is backend.state
    assert_cleared(state, "unsupported", "matching_device_not_found", 2)
    assert backend.move_dpi_stage(1) is state
    assert backend.move_scroll_mode(1) is state
    assert backend.set_scroll_mode("free_spin") is state
    assert factory.calls == 1 and device.stage_writes == device.scroll_writes == []
