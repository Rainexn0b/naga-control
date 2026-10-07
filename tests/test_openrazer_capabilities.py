"""Capability contracts exercised with existing fakes, never real device owners."""

from dataclasses import replace
from typing import Literal, cast

import pytest
from test_openrazer_backend import DbusInteger, FakeDevice, FakeManager
from test_openrazer_mode import FakeDbus, ModeDevice

from naga_control.adapters.evdev.discovery import EventNode, NagaConnection
from naga_control.adapters.openrazer.backend import OpenRazerBackend
from naga_control.adapters.openrazer.capabilities import (
    InvalidCapabilityResponseError,
    MissingCapabilityError,
    read_hardware_state,
)
from naga_control.adapters.openrazer.mode import read_device_mode, set_device_mode
from naga_control.domain.hardware import DeviceModeError, HardwareDpiStage, HardwareState

_HEALTHY = HardwareState(
    status="available",
    generation=7,
    transport="wired",
    dpi=HardwareDpiStage(800, 800),
    dpi_stages=(
        HardwareDpiStage(400, 500),
        HardwareDpiStage(800, 900),
        HardwareDpiStage(1200, 1300),
    ),
    active_dpi_stage=2,
    max_dpi=50000,
    scroll_mode="tactile",
    scroll_mode_options=("tactile", "free_spin", "precision_tactile"),
    scroll_acceleration=True,
    scroll_smart_reel=False,
    poll_rate=1000,
    battery_percent=88.0,
    charging=False,
    firmware_version="v1.0",
)
_OPTIONAL_FIELDS = (
    ("poll_rate", "poll_rate"),
    ("is_charging", "charging"),
    ("battery_level", "battery_percent"),
    ("firmware_version", "firmware_version"),
)
_TOPOLOGY = (
    NagaConnection(
        usb_path="/usb/test",
        vendor_id="1532",
        product_id="00e7",
        transport="wired",
        serial="test-only",
        physical_path="test-only",
        nodes=(EventNode("/not-a-device", "/usb/test", "00", "1532", "00e7"),),
    ),
)


@pytest.mark.parametrize(("attribute", "field"), _OPTIONAL_FIELDS)
@pytest.mark.parametrize("failure", ["missing", "raising"])
def test_optional_getter_failures_preserve_required_and_other_optional_values(
    attribute: str, field: str, failure: str
) -> None:
    device = FakeDevice(
        missing=attribute if failure == "missing" else None,
        failing=attribute if failure == "raising" else None,
    )

    state = read_hardware_state(device, 7, "wired")

    assert state == replace(_HEALTHY, **{field: None})
    assert device.stage_writes == device.scroll_writes == []


@pytest.mark.parametrize(
    ("attribute", "field", "reply", "expected"),
    [
        ("poll_rate", "poll_rate", None, None),
        ("poll_rate", "poll_rate", True, None),
        ("poll_rate", "poll_rate", 1000.0, None),
        ("poll_rate", "poll_rate", "1000", None),
        ("poll_rate", "poll_rate", "unknown", None),
        ("poll_rate", "poll_rate", [1000], None),
        ("poll_rate", "poll_rate", {"rate": 1000}, None),
        # Optional poll-rate reads validate type, not supported rates or range.
        ("poll_rate", "poll_rate", -1, -1),
        ("poll_rate", "poll_rate", 0, 0),
        ("poll_rate", "poll_rate", 2000, 2000),
        ("poll_rate", "poll_rate", DbusInteger(500), DbusInteger(500)),
        ("is_charging", "charging", None, None),
        ("is_charging", "charging", True, True),
        ("is_charging", "charging", False, False),
        ("is_charging", "charging", 0, None),
        ("is_charging", "charging", 1, None),
        ("is_charging", "charging", -1, None),
        ("is_charging", "charging", 2, None),
        ("is_charging", "charging", 1.0, None),
        ("is_charging", "charging", "true", None),
        ("is_charging", "charging", "unknown", None),
        ("is_charging", "charging", [], None),
        ("battery_level", "battery_percent", None, None),
        ("battery_level", "battery_percent", True, None),
        ("battery_level", "battery_percent", False, None),
        ("battery_level", "battery_percent", "88", None),
        ("battery_level", "battery_percent", "unknown", None),
        ("battery_level", "battery_percent", [88], None),
        ("battery_level", "battery_percent", {"percent": 88}, None),
        ("battery_level", "battery_percent", -1, None),
        ("battery_level", "battery_percent", 100.01, None),
        ("battery_level", "battery_percent", float("nan"), None),
        ("battery_level", "battery_percent", float("inf"), None),
        ("battery_level", "battery_percent", float("-inf"), None),
        ("battery_level", "battery_percent", 0, 0.0),
        ("battery_level", "battery_percent", 100, 100.0),
        ("battery_level", "battery_percent", 42.5, 42.5),
        ("battery_level", "battery_percent", DbusInteger(88), 88.0),
        ("firmware_version", "firmware_version", None, None),
        ("firmware_version", "firmware_version", True, None),
        ("firmware_version", "firmware_version", -1, None),
        ("firmware_version", "firmware_version", 1.0, None),
        ("firmware_version", "firmware_version", b"v1.0", None),
        ("firmware_version", "firmware_version", [], None),
        ("firmware_version", "firmware_version", "", None),
        ("firmware_version", "firmware_version", " \t\n", None),
        # Nonblank firmware is preserved verbatim, without parsing or sentinels.
        ("firmware_version", "firmware_version", "unknown", "unknown"),
        ("firmware_version", "firmware_version", " v1.0 ", " v1.0 "),
    ],
)
def test_optional_reply_contract(
    attribute: str, field: str, reply: object, expected: object
) -> None:
    device = FakeDevice()
    setattr(device, attribute, reply)

    state = read_hardware_state(device, 7, "wired")

    assert state == replace(_HEALTHY, **{field: expected})
    assert type(getattr(state, field)) is type(expected)


@pytest.mark.parametrize(
    "reply", [pytest.param(10**400, id="positive"), pytest.param(-(10**400), id="negative")]
)
def test_extreme_battery_integers_preserve_available_state_and_recover(reply: int) -> None:
    degraded = FakeDevice()
    degraded.battery_level = cast(float, reply)
    healthy = FakeDevice()
    managers = [FakeManager((degraded,)), FakeManager((healthy,))]
    backend = OpenRazerBackend(lambda: managers.pop(0))

    initial = backend.rescan(_TOPOLOGY)
    assert initial == replace(_HEALTHY, generation=initial.generation, battery_percent=None)
    assert read_hardware_state(degraded, 7, "wired") == replace(_HEALTHY, battery_percent=None)
    recovered = backend.rescan(_TOPOLOGY)

    assert recovered == replace(_HEALTHY, generation=recovered.generation)
    assert recovered.generation > initial.generation
    assert backend.state is recovered
    assert initial.battery_percent is None
    assert managers == []
    assert degraded.stage_writes == healthy.stage_writes == []
    assert degraded.scroll_writes == healthy.scroll_writes == []


def test_simultaneous_optional_failures_do_not_hide_required_state() -> None:
    device = FakeDevice(missing="poll_rate", failing="battery_level")
    device.is_charging = cast(bool, "unknown")
    device.firmware_version = " "

    state = OpenRazerBackend(lambda: FakeManager((device,))).rescan(_TOPOLOGY)

    assert state == replace(
        _HEALTHY,
        generation=state.generation,
        poll_rate=None,
        battery_percent=None,
        charging=None,
        firmware_version=None,
    )
    assert device.stage_writes == device.scroll_writes == []


@pytest.mark.parametrize(("attribute", "field"), _OPTIONAL_FIELDS)
@pytest.mark.parametrize("failure", ["missing", "raising", "malformed"])
def test_later_healthy_rescan_recovers_each_optional_value(
    attribute: str, field: str, failure: str
) -> None:
    degraded = FakeDevice(
        missing=attribute if failure == "missing" else None,
        failing=attribute if failure == "raising" else None,
    )
    if failure == "malformed":
        setattr(degraded, attribute, [])
    healthy = FakeDevice()
    managers = [FakeManager((degraded,)), FakeManager((healthy,))]
    backend = OpenRazerBackend(lambda: managers.pop(0))

    initial = backend.rescan(_TOPOLOGY)
    recovered = backend.rescan(_TOPOLOGY)

    assert initial == replace(_HEALTHY, generation=initial.generation, **{field: None})
    assert recovered == replace(_HEALTHY, generation=recovered.generation)
    assert recovered.generation > initial.generation
    assert backend.state is recovered
    assert getattr(initial, field) is None
    assert managers == []
    assert degraded.stage_writes == healthy.stage_writes == []
    assert degraded.scroll_writes == healthy.scroll_writes == []


@pytest.mark.parametrize(
    ("attribute", "reply"),
    [
        pytest.param("_dpi", (99, 800), id="dpi-below-range"),
        pytest.param("_dpi", (800, 50001), id="dpi-above-range"),
        pytest.param("_dpi", (True, 800), id="dpi-bool"),
        pytest.param("_dpi", (DbusInteger(800), 800), id="dpi-int-subclass"),
        pytest.param("_dpi", ("800", 800), id="dpi-nonnumeric"),
        pytest.param("_dpi_stages", None, id="stages-null"),
        pytest.param("_dpi_stages", "unknown", id="stages-nonsequence"),
        pytest.param("_dpi_stages", (1,), id="stages-missing-list"),
        pytest.param("_dpi_stages", (1, ((800, 800),), 0), id="stages-extra-field"),
        pytest.param("_dpi_stages", (True, ((800, 800),)), id="active-bool"),
        pytest.param("_dpi_stages", (DbusInteger(1), ((800, 800),)), id="active-int-subclass"),
        pytest.param("_dpi_stages", ("1", ((800, 800),)), id="active-nonnumeric"),
        pytest.param("_dpi_stages", (-1, ((800, 800),)), id="active-negative"),
        pytest.param("_dpi_stages", (0, ((800, 800),)), id="active-zero"),
        pytest.param("_dpi_stages", (2, ((800, 800),)), id="active-out-of-range"),
        pytest.param("_dpi_stages", (1, ()), id="stages-empty"),
        pytest.param("_dpi_stages", (1, ((800, 800),) * 6), id="stages-too-many"),
        pytest.param("_dpi_stages", (1, None), id="stage-list-null"),
        pytest.param("_dpi_stages", (1, (800,)), id="stage-not-a-pair"),
        pytest.param("_dpi_stages", (1, ((800,),)), id="stage-pair-too-short"),
        pytest.param("_dpi_stages", (1, ((800, 800, 800),)), id="stage-pair-too-long"),
        pytest.param("_dpi_stages", (1, ((800.0, 800),)), id="stage-float"),
        pytest.param("_dpi_stages", (1, ((800, 99),)), id="stage-below-range"),
        pytest.param("max_dpi", 50001, id="max-dpi-above-range"),
        pytest.param("max_dpi", 99, id="max-dpi-below-range"),
        pytest.param("max_dpi", "50000", id="max-dpi-nonnumeric"),
        pytest.param("_scroll_mode", None, id="mode-null"),
        pytest.param("_scroll_mode", True, id="mode-bool"),
        pytest.param("_scroll_mode", 0.0, id="mode-float"),
        pytest.param("_scroll_mode", [], id="mode-non-scalar"),
        pytest.param("_scroll_mode", -1, id="mode-negative"),
        pytest.param("_scroll_mode", 3, id="mode-out-of-range"),
        pytest.param("_scroll_mode", "unknown", id="mode-unknown"),
        pytest.param("_scroll_mode", "0", id="mode-numeric-string"),
        pytest.param("_scroll_mode_options", None, id="options-null"),
        pytest.param("_scroll_mode_options", "tactile", id="options-not-sequence"),
        pytest.param("_scroll_mode_options", (), id="options-empty"),
        pytest.param("_scroll_mode_options", (0, "tactile"), id="options-duplicate-after-parse"),
        pytest.param("_scroll_mode_options", ("unknown",), id="options-unknown"),
        pytest.param("_scroll_mode_options", (1, 2), id="current-mode-not-supported"),
        pytest.param("_scroll_acceleration", 1, id="acceleration-not-bool"),
        pytest.param("_scroll_smart_reel", None, id="smart-reel-null"),
    ],
)
def test_malformed_required_replies_report_parse_error_and_clear_previous_state(
    attribute: str, reply: object
) -> None:
    device = FakeDevice()
    backend = OpenRazerBackend(lambda: FakeManager((device,)))
    assert backend.rescan(_TOPOLOGY).status == "available"
    setattr(device, attribute, reply)

    with pytest.raises(InvalidCapabilityResponseError):
        read_hardware_state(device, 7, "wired")
    state = backend.rescan(_TOPOLOGY)

    assert state.error is not None and state.error.code == "invalid_response"
    assert state == HardwareState("unsupported", state.generation, error=state.error)
    assert device.stage_writes == device.scroll_writes == []


@pytest.mark.parametrize(
    "attribute",
    [
        "dpi",
        "dpi_stages",
        "max_dpi",
        "scroll_mode",
        "scroll_mode_options",
        "scroll_acceleration",
        "scroll_smart_reel",
    ],
)
def test_missing_required_property_is_unsupported_not_a_parse_error(attribute: str) -> None:
    device = FakeDevice(missing=attribute)

    with pytest.raises(MissingCapabilityError) as error:
        read_hardware_state(device, 7, "wired")
    state = OpenRazerBackend(lambda: FakeManager((device,))).rescan(_TOPOLOGY)

    assert isinstance(error.value.__cause__, AttributeError)
    assert state.error is not None and state.error.code == "unsupported_capability"
    assert state == HardwareState("unsupported", state.generation, error=state.error)
    assert device.stage_writes == device.scroll_writes == []


def test_valid_list_stages_and_numeric_scroll_options_are_normalized() -> None:
    device = FakeDevice(
        dpi_stages=[1, [[100, 50000], [50000, 100]]],
        scroll_mode=DbusInteger(2),
        scroll_mode_options=[DbusInteger(2), 0],
    )

    state = read_hardware_state(device, 7, "wired")

    assert state == replace(
        _HEALTHY,
        active_dpi_stage=1,
        dpi_stages=(HardwareDpiStage(100, 50000), HardwareDpiStage(50000, 100)),
        scroll_mode="precision_tactile",
        scroll_mode_options=("precision_tactile", "tactile"),
    )


@pytest.mark.parametrize("reply", [None, True, 0, b"3:0", [], "", "unknown", "1:0", "3:1"])
def test_malformed_device_mode_reply_is_a_parse_error_not_unsupported(reply: object) -> None:
    dbus = FakeDbus(reply)

    with pytest.raises(DeviceModeError) as error:
        read_device_mode(ModeDevice(dbus))

    assert error.value.code == "invalid_response"
    assert dbus.reads == 1
    assert dbus.writes == []


@pytest.mark.parametrize("missing", ["getDeviceMode", "setDeviceMode", "get_dbus_method"])
def test_missing_device_mode_method_is_unsupported_not_a_parse_error(
    missing: Literal["getDeviceMode", "setDeviceMode", "get_dbus_method"],
) -> None:
    dbus = FakeDbus()
    dbus.missing = missing
    device = ModeDevice(cast(FakeDbus, object()) if missing == "get_dbus_method" else dbus)

    with pytest.raises(DeviceModeError) as error:
        set_device_mode(device, "software")

    assert error.value.code == "unsupported"
    assert dbus.reads == (1 if missing == "setDeviceMode" else 0)
    assert dbus.writes == []
