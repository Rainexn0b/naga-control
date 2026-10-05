"""Mode requests use fake OpenRazer D-Bus objects, never real hardware."""

import pytest
from test_openrazer_backend import FakeDevice, FakeManager

from naga_control.adapters.evdev.discovery import EventNode, NagaConnection, Transport
from naga_control.adapters.openrazer.backend import OpenRazerBackend
from naga_control.domain.hardware import DeviceModeError


class FakeDbus:
    def __init__(self, value: object = "0:0") -> None:
        self.value = value
        self.reads = 0
        self.writes: list[tuple[int, int]] = []
        self.missing: str | None = None
        self.fail: str | None = None
        self.ignore_write = False

    def get_dbus_method(self, name: str, interface: str) -> object:
        assert interface == "razer.device.misc"
        if self.fail == "lookup":
            raise RuntimeError("fake D-Bus lookup failed")
        if name == self.missing:
            raise AttributeError(name)
        if name == "getDeviceMode":
            return self.read
        if name == "setDeviceMode":
            return self.write
        raise AssertionError(name)

    def read(self) -> object:
        self.reads += 1
        if self.fail == "read" or (self.fail == "readback" and self.reads == 2):
            raise RuntimeError("fake D-Bus read failed")
        return self.value

    def write(self, first: int, second: int) -> None:
        if self.fail == "write":
            raise RuntimeError("fake D-Bus write failed")
        self.writes.append((first, second))
        if not self.ignore_write:
            self.value = f"{first}:{second}"


class ModeDevice(FakeDevice):
    _dbus: FakeDbus

    def __init__(self, dbus: FakeDbus | None = None, *, failing: str | None = None) -> None:
        super().__init__(failing=failing)
        self._dbus = dbus or FakeDbus()

    @property
    def dbus(self) -> FakeDbus:
        return self._dbus


def _connection(transport: Transport) -> NagaConnection:
    product = "00e7" if transport == "wired" else "00e8"
    return NagaConnection(
        usb_path="/usb/test",
        vendor_id="1532",
        product_id=product,
        transport=transport,
        serial="test-only",
        physical_path="test-only",
        nodes=(EventNode("/not-a-device", "/usb/test", "00", "1532", product),),
    )


def _backend(dbus: FakeDbus | None = None) -> tuple[OpenRazerBackend, FakeDbus]:
    device = ModeDevice(dbus)
    backend = OpenRazerBackend(lambda: FakeManager((device,)))
    assert backend.rescan((_connection("wired"),)).status == "available"
    return backend, device.dbus


def test_read_and_set_mode_use_exact_codes_and_skip_redundant_writes() -> None:
    backend, dbus = _backend()
    assert backend.read_device_mode() == "firmware"
    assert backend.set_device_mode("firmware") == "firmware"
    assert dbus.writes == []
    assert backend.set_device_mode("software") == "software"
    assert backend.read_device_mode() == "software"
    assert backend.set_device_mode("firmware") == "firmware"
    assert dbus.writes == [(3, 0), (0, 0)]


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        ("missing_get", "unsupported"),
        ("missing_set", "unsupported"),
        ("unknown", "invalid_response"),
        ("read", "read_failed"),
        ("write", "write_failed"),
        ("readback", "read_failed"),
        ("mismatch", "mismatch"),
    ],
)
def test_set_mode_never_claims_success_without_confirmed_readback(
    setup: str, expected: str
) -> None:
    backend, dbus = _backend()
    if setup == "missing_get":
        dbus.missing = "getDeviceMode"
    elif setup == "missing_set":
        dbus.missing = "setDeviceMode"
    elif setup == "unknown":
        dbus.value = "1:0"
    elif setup == "mismatch":
        dbus.ignore_write = True
    else:
        dbus.fail = setup

    with pytest.raises(DeviceModeError) as error:
        backend.set_device_mode("software")
    assert error.value.code == expected
    assert dbus.writes == ([(3, 0)] if setup in {"readback", "mismatch"} else [])


def test_read_mode_rejects_invalid_response_and_unavailable_device() -> None:
    backend, dbus = _backend()
    dbus.value = 0
    with pytest.raises(DeviceModeError, match="unknown") as error:
        backend.read_device_mode()
    assert error.value.code == "invalid_response"

    backend.rescan(())
    with pytest.raises(DeviceModeError) as error:
        backend.read_device_mode()
    assert error.value.code == "unavailable"
    assert dbus.writes == []


def test_read_mode_reports_missing_and_failed_dbus_access() -> None:
    backend, dbus = _backend()
    dbus.missing = "getDeviceMode"
    with pytest.raises(DeviceModeError) as error:
        backend.read_device_mode()
    assert error.value.code == "unsupported"

    dbus.missing = None
    dbus.fail = "lookup"
    with pytest.raises(DeviceModeError) as error:
        backend.read_device_mode()
    assert error.value.code == "read_failed"
    assert dbus.writes == []


def test_invalid_mode_does_not_access_dbus() -> None:
    backend, dbus = _backend()
    with pytest.raises(ValueError, match="software or firmware"):
        backend.set_device_mode("unknown")  # type: ignore[arg-type]
    assert dbus.reads == 0
    assert dbus.writes == []


def test_mode_operation_reacquires_a_woken_client_and_never_writes_old_client() -> None:
    sleeping = ModeDevice(failing="dpi")
    awake = ModeDevice()
    managers = [FakeManager((sleeping,)), FakeManager((awake,))]
    backend = OpenRazerBackend(lambda: managers.pop(0))
    assert backend.rescan((_connection("wired"),)).status == "unavailable"

    assert backend.set_device_mode("software") == "software"
    assert sleeping.dbus.writes == []
    assert awake.dbus.writes == [(3, 0)]


def test_conflicting_transports_cannot_issue_mode_calls() -> None:
    backend, dbus = _backend()
    backend.rescan((_connection("wired"), _connection("hyperspeed")))
    with pytest.raises(DeviceModeError) as error:
        backend.set_device_mode("software")
    assert error.value.code == "unavailable"
    assert dbus.reads == 0
    assert dbus.writes == []
