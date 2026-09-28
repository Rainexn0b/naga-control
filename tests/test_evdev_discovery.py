from collections.abc import Iterable, Mapping

from naga_control.adapters.evdev.discovery import (
    EventNode,
    UdevDevice,
    discover_naga_connections,
    group_naga_nodes,
)


class FakeAttributes:
    def __init__(self, values: Mapping[str, object]) -> None:
        self._values = values

    def get(self, attribute: str) -> object:
        return self._values.get(attribute)


class FakeDevice:
    def __init__(
        self,
        *,
        device_node: str | None = None,
        device_type: str | None = None,
        sys_name: str = "",
        sys_path: str = "",
        attributes: Mapping[str, object] | None = None,
        properties: Mapping[str, object] | None = None,
        parents: Mapping[tuple[str, str | None], UdevDevice] | None = None,
    ) -> None:
        self.device_node = device_node
        self.device_type = device_type
        self.sys_name = sys_name
        self.sys_path = sys_path
        self.is_initialized = True
        self.attributes = FakeAttributes(attributes or {})
        self.properties = properties or {}
        self._parents = parents or {}

    def find_parent(self, subsystem: str, device_type: str | None = None) -> UdevDevice | None:
        return self._parents.get((subsystem, device_type))


class FakeContext:
    def __init__(
        self,
        input_devices: Iterable[UdevDevice],
        usb_devices: Iterable[UdevDevice],
    ) -> None:
        self._input_devices = tuple(input_devices)
        self._usb_devices = tuple(usb_devices)

    def list_devices(self, **kwargs: str) -> Iterable[UdevDevice]:
        if kwargs == {"subsystem": "input"}:
            return self._input_devices
        assert kwargs == {"subsystem": "usb"}
        return self._usb_devices


def test_group_naga_nodes_filters_and_groups_by_physical_usb_parent() -> None:
    candidates = (
        _node("/dev/input/event8", "/usb/receiver", "02", "00E8"),
        _node("/dev/input/event6", "/usb/receiver", "00", "00e8"),
        _node("/dev/input/event7", "/usb/receiver", "01", "00e8"),
        _node("/dev/input/event1", "", "00", "00e8"),
        _node("/dev/input/event2", "/usb/dock", "00", "00a4"),
        EventNode("/dev/input/event3", "/usb/other", "00", "1234", "00e8"),
    )

    connections = group_naga_nodes(candidates)

    assert len(connections) == 1
    assert connections[0].transport == "hyperspeed"
    assert tuple(node.interface_number for node in connections[0].nodes) == ("00", "01", "02")


def test_wired_and_wireless_with_same_serial_remain_conflicting_connections() -> None:
    connections = group_naga_nodes(
        (
            _node("/dev/input/event1", "/usb/wired", "00", "00e7", serial="same"),
            _node("/dev/input/event2", "/usb/wireless", "00", "00e8", serial="same"),
        )
    )

    assert [connection.transport for connection in connections] == ["wired", "hyperspeed"]


def test_discovery_requires_usb_device_and_interface_ancestors() -> None:
    usb = FakeDevice(
        device_type="usb_device",
        sys_path="/sys/devices/usb/receiver",
        attributes={"idVendor": b"1532", "idProduct": b"00E8", "serial": b"secret"},
        properties={"ID_PATH": "pci-0000:00-usb-0:1"},
    )
    interface = FakeDevice(attributes={"bInterfaceNumber": b"02"})
    parents: dict[tuple[str, str | None], UdevDevice] = {
        ("usb", "usb_device"): usb,
        ("usb", "usb_interface"): interface,
    }
    physical_event = FakeDevice(
        device_node="/dev/input/event5",
        sys_name="event5",
        parents=parents,
    )
    virtual_event = FakeDevice(device_node="/dev/input/event99", sys_name="event99")

    connections = discover_naga_connections(FakeContext((physical_event, virtual_event), (usb,)))

    assert len(connections) == 1
    assert connections[0].nodes[0].event_path == "/dev/input/event5"
    assert connections[0].serial == "secret"


def test_discovery_reports_supported_usb_before_event_nodes_initialize() -> None:
    usb = FakeDevice(
        device_type="usb_device",
        sys_path="/sys/devices/usb/wired",
        attributes={"idVendor": "1532", "idProduct": "00e7"},
    )

    connections = discover_naga_connections(FakeContext((), (usb,)))

    assert len(connections) == 1
    assert connections[0].transport == "wired"
    assert connections[0].nodes == ()


def test_discovery_reports_dual_transport_when_one_has_no_event_nodes() -> None:
    wired = FakeDevice(
        device_type="usb_device",
        sys_path="/sys/devices/usb/wired",
        attributes={"idVendor": "1532", "idProduct": "00e7"},
    )
    wireless = FakeDevice(
        device_type="usb_device",
        sys_path="/sys/devices/usb/wireless",
        attributes={"idVendor": "1532", "idProduct": "00e8"},
    )

    connections = discover_naga_connections(FakeContext((), (wired, wireless)))

    assert [connection.transport for connection in connections] == ["wired", "hyperspeed"]
    assert all(not connection.nodes for connection in connections)


def _node(
    event_path: str,
    usb_path: str,
    interface: str,
    product: str,
    *,
    serial: str | None = None,
) -> EventNode:
    return EventNode(event_path, usb_path, interface, "1532", product, serial=serial)
