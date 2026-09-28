from collections.abc import Iterable

from naga_control.adapters.evdev.discovery import EventNode, NagaConnection, Transport
from naga_control.adapters.openrazer.backend import OpenRazerBackend
from naga_control.domain.defaults import default_configuration


class FakeDevice:
    def __init__(
        self,
        *,
        vendor_id: int = 0x1532,
        product_id: int = 0x00E7,
        dpi: object = (800, 800),
        dpi_stages: object = (2, ((400, 500), (800, 900), (1200, 1300))),
        scroll_mode: object = 0,
        scroll_mode_options: object = ("tactile", "free_spin", "precision_tactile"),
        missing: str | None = None,
        failing: str | None = None,
    ) -> None:
        self._vid = vendor_id
        self._pid = product_id
        self._dpi = dpi
        self._dpi_stages = dpi_stages
        self._scroll_mode = scroll_mode
        self._scroll_mode_options = scroll_mode_options
        self._missing = missing
        self._failing = failing
        self.max_dpi = 50000
        self._scroll_acceleration = True
        self._scroll_smart_reel = False
        self.battery_level = 88.0
        self.is_charging = False
        self.firmware_version = "v1.0"
        self.poll_rate = 1000
        self.brightness = 75.0
        self.fx = _Fx()
        self.stage_writes: list[object] = []
        self.scroll_writes: list[object] = []
        self.idle_writes: list[int] = []
        self.threshold_writes: list[int] = []
        self.acceleration_writes: list[bool] = []
        self.smart_reel_writes: list[bool] = []

    def __getattribute__(self, name: str) -> object:
        missing = object.__getattribute__(self, "_missing") if name != "_missing" else None
        failing = object.__getattribute__(self, "_failing") if name != "_failing" else None
        if name == missing:
            raise AttributeError(name)
        if name == failing:
            raise RuntimeError("fake client failure")
        return object.__getattribute__(self, name)

    @property
    def dpi(self) -> object:
        return self._dpi

    @property
    def dpi_stages(self) -> object:
        return self._dpi_stages

    @dpi_stages.setter
    def dpi_stages(self, value: object) -> None:
        self.stage_writes.append(value)
        self._dpi_stages = value

    @property
    def scroll_mode(self) -> object:
        return self._scroll_mode

    @scroll_mode.setter
    def scroll_mode(self, value: object) -> None:
        if self._failing == "scroll_mode_set":
            raise RuntimeError("fake scroll-mode write failed")
        self.scroll_writes.append(value)
        self._scroll_mode = value

    @property
    def scroll_mode_options(self) -> object:
        return self._scroll_mode_options

    @property
    def scroll_acceleration(self) -> bool:
        return self._scroll_acceleration

    @scroll_acceleration.setter
    def scroll_acceleration(self, value: bool) -> None:
        self.acceleration_writes.append(value)
        self._scroll_acceleration = value

    @property
    def scroll_smart_reel(self) -> bool:
        return self._scroll_smart_reel

    @scroll_smart_reel.setter
    def scroll_smart_reel(self, value: bool) -> None:
        self.smart_reel_writes.append(value)
        self._scroll_smart_reel = value

    def set_idle_time(self, seconds: int) -> None:
        self.idle_writes.append(seconds)

    def set_low_battery_threshold(self, percent: int) -> None:
        self.threshold_writes.append(percent)


class _Zone:
    def __init__(self, calls: list[str], prefix: str) -> None:
        self._calls = calls
        self._prefix = prefix
        self.brightness = 0.0

    def none(self) -> None:
        self._calls.append(f"{self._prefix}:none")

    def static(self, red: int, green: int, blue: int) -> None:
        self._calls.append(f"{self._prefix}:static")

    def spectrum(self) -> None:
        self._calls.append(f"{self._prefix}:spectrum")

    def breath_single(self, red: int, green: int, blue: int) -> None:
        self._calls.append(f"{self._prefix}:breath")

    def reactive(self, red: int, green: int, blue: int, speed: int) -> None:
        self._calls.append(f"{self._prefix}:reactive")

    def wave(self, direction: int) -> None:
        self._calls.append(f"{self._prefix}:wave")


class _Misc:
    def __init__(self, calls: list[str]) -> None:
        self.logo = _Zone(calls, "logo")
        self.scroll_wheel = _Zone(calls, "scroll")


class _Fx:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.misc = _Misc(self.calls)
        self.grid = _Zone(self.calls, "grid")

    def __getattr__(self, name: str) -> object:
        return getattr(self.grid, name)


def test_apply_profile_settings_writes_every_step_and_collects_partial_failures() -> None:
    device = FakeDevice(failing="scroll_mode_set")
    backend = OpenRazerBackend(lambda: FakeManager((device,)))
    backend.rescan((_connection("wired"),))
    profile = default_configuration().profile("default")

    state, failures = backend.apply_profile_settings(profile)

    assert state.status == "available"
    assert state.battery_percent == 88.0
    assert state.firmware_version == "v1.0"
    assert [failure.setting for failure in failures] == ["scroll_mode"]
    assert device.stage_writes == [
        (2, ((800, 800), (1600, 1600), (2400, 2400), (3200, 3200), (5000, 5000)))
    ]
    assert device.acceleration_writes == [False]
    assert device.smart_reel_writes == [False]
    assert device.idle_writes == [300]
    assert device.threshold_writes == [20]
    assert device.poll_rate == 1000
    assert device.brightness == 100
    assert device.fx.calls == ["grid:static", "logo:static", "scroll:static"]


def test_apply_profile_settings_reports_unavailable_hardware() -> None:
    sleeping = FakeDevice(failing="dpi")
    managers = [FakeManager((sleeping,)), FakeManager((sleeping,))]
    backend = OpenRazerBackend(lambda: managers.pop(0))
    backend.rescan((_connection("wired"),))

    state, failures = backend.apply_profile_settings(default_configuration().profile("default"))

    assert state.status == "unavailable"
    assert [failure.setting for failure in failures] == ["profile"]


class FakeManager:
    def __init__(self, devices: Iterable[object]) -> None:
        self._devices = tuple(devices)

    @property
    def devices(self) -> Iterable[object]:
        return self._devices


class DbusInteger(int):
    pass


def test_rescan_selects_only_exact_vid_pid_and_replaces_manager_snapshot() -> None:
    wrong_transport = FakeDevice(product_id=0x00E8)
    first = FakeDevice()
    second = FakeDevice(dpi=(1600, 1700))
    managers = [FakeManager((wrong_transport, first)), FakeManager((second,))]

    backend = OpenRazerBackend(lambda: managers.pop(0))

    initial = backend.rescan((_connection("wired"),))
    refreshed = backend.rescan((_connection("wired"),))

    assert initial.status == "available"
    assert initial.dpi is not None and initial.dpi.x == 800
    assert refreshed.status == "available"
    assert refreshed.dpi is not None and refreshed.dpi.x == 1600
    assert not hasattr(refreshed, "serial")
    assert first.stage_writes == []
    assert wrong_transport.stage_writes == []


def test_rescan_accepts_dbus_integer_identifier_subclasses() -> None:
    device = FakeDevice(vendor_id=DbusInteger(0x1532), product_id=DbusInteger(0x00E8))

    state = OpenRazerBackend(lambda: FakeManager((device,))).rescan((_connection("hyperspeed"),))

    assert state.status == "available"


def test_rescan_without_ready_nodes_or_with_conflicts_never_constructs_a_manager() -> None:
    factory_calls = 0

    def factory() -> FakeManager:
        nonlocal factory_calls
        factory_calls += 1
        return FakeManager(())

    backend = OpenRazerBackend(factory)

    no_nodes = backend.rescan((_connection("wired", nodes=False),))
    dual_transport = backend.rescan((_connection("wired"), _connection("hyperspeed")))
    duplicate_transport = backend.rescan((_connection("wired"), _connection("wired")))

    assert no_nodes.status == "unavailable"
    assert no_nodes.error is not None and no_nodes.error.code == "input_nodes_unavailable"
    assert dual_transport.status == "transport_conflict"
    assert duplicate_transport.status == "multiple_device_conflict"
    assert factory_calls == 0


def test_capability_and_client_failures_clear_the_observed_state() -> None:
    missing = OpenRazerBackend(lambda: FakeManager((FakeDevice(missing="scroll_smart_reel"),)))
    invalid = OpenRazerBackend(lambda: FakeManager((FakeDevice(dpi=(99, 800)),)))
    unavailable = OpenRazerBackend(lambda: FakeManager((FakeDevice(failing="dpi"),)))

    missing_state = missing.rescan((_connection("wired"),))
    invalid_state = invalid.rescan((_connection("wired"),))
    unavailable_state = unavailable.rescan((_connection("wired"),))

    assert missing_state.status == "unsupported"
    assert missing_state.error is not None and missing_state.error.code == "unsupported_capability"
    assert invalid_state.status == "unsupported"
    assert invalid_state.error is not None and invalid_state.error.code == "invalid_response"
    assert unavailable_state.status == "unavailable"
    assert (
        unavailable_state.error is not None and unavailable_state.error.code == "device_unavailable"
    )
    assert missing_state.dpi is None
    assert invalid_state.dpi_stages == ()


def test_dpi_stage_moves_clamp_without_writes_and_preserve_asymmetric_pairs() -> None:
    device = FakeDevice(dpi_stages=(2, ((400, 450), (800, 850), (1200, 1250))))
    backend = OpenRazerBackend(lambda: FakeManager((device,)))
    backend.rescan((_connection("wired"),))

    up = backend.move_dpi_stage(1)
    boundary = backend.move_dpi_stage(1)
    down = backend.move_dpi_stage(-1)

    assert up.active_dpi_stage == 3
    assert boundary.active_dpi_stage == 3
    assert down.active_dpi_stage == 2
    assert device.stage_writes == [
        (3, ((400, 450), (800, 850), (1200, 1250))),
        (2, ((400, 450), (800, 850), (1200, 1250))),
    ]


def test_action_reacquires_a_client_after_an_unavailable_rescan() -> None:
    sleeping = FakeDevice(failing="dpi")
    awake = FakeDevice()
    managers = [FakeManager((sleeping,)), FakeManager((awake,))]
    backend = OpenRazerBackend(lambda: managers.pop(0))

    unavailable = backend.rescan((_connection("wired"),))
    recovered = backend.move_dpi_stage(1)

    assert unavailable.status == "unavailable"
    assert recovered.status == "available"
    assert recovered.active_dpi_stage == 3
    assert awake.stage_writes == [
        (3, ((400, 500), (800, 900), (1200, 1300))),
    ]


def test_scroll_actions_use_canonical_cycle_order_and_only_supported_modes() -> None:
    device = FakeDevice(
        scroll_mode=2,
        scroll_mode_options=("precision_tactile", "tactile"),
    )
    backend = OpenRazerBackend(lambda: FakeManager((device,)))
    backend.rescan((_connection("wired"),))

    next_mode = backend.move_scroll_mode(1)
    previous_mode = backend.move_scroll_mode(-1)
    unavailable = backend.set_scroll_mode("free_spin")

    assert next_mode.scroll_mode == "tactile"
    assert previous_mode.scroll_mode == "precision_tactile"
    assert unavailable.status == "unsupported"
    assert unavailable.error is not None and unavailable.error.code == "unsupported_capability"
    assert device.scroll_writes == [0, 2]


def _connection(transport: Transport, *, nodes: bool = True) -> NagaConnection:
    product_id = "00e7" if transport == "wired" else "00e8"
    event_nodes = (
        (EventNode("/not-a-device", "/usb/test", "00", "1532", product_id),) if nodes else ()
    )
    return NagaConnection(
        usb_path="/usb/test",
        vendor_id="1532",
        product_id=product_id,
        transport=transport,
        serial="test-only",
        physical_path="test-only",
        nodes=event_nodes,
    )
