"""Discover Naga V3 Pro event nodes through their physical USB ancestry."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib import import_module
from typing import Literal, Protocol, cast


class UdevAttributes(Protocol):
    def get(self, attribute: str) -> object: ...


class UdevDevice(Protocol):
    @property
    def device_node(self) -> str | None: ...

    @property
    def sys_name(self) -> str: ...

    @property
    def sys_path(self) -> str: ...

    @property
    def is_initialized(self) -> bool: ...

    @property
    def device_type(self) -> str | None: ...

    @property
    def attributes(self) -> UdevAttributes: ...

    @property
    def properties(self) -> Mapping[str, object]: ...

    def find_parent(
        self, subsystem: str, device_type: str | None = None
    ) -> "UdevDevice | None": ...


class UdevContext(Protocol):
    def list_devices(self, **kwargs: str) -> Iterable[UdevDevice]: ...


class _ContextFactory(Protocol):
    def __call__(self) -> UdevContext: ...


class _DeviceLookup(Protocol):
    def from_device_number(
        self, context: UdevContext, device_type: str, device_number: int
    ) -> UdevDevice: ...


Transport = Literal["wired", "hyperspeed"]

VENDOR_ID = "1532"
PRODUCT_TRANSPORTS: dict[str, Transport] = {
    "00e7": "wired",
    "00e8": "hyperspeed",
}


@dataclass(frozen=True, slots=True)
class EventNode:
    event_path: str
    usb_path: str
    interface_number: str
    vendor_id: str
    product_id: str
    serial: str | None = None
    physical_path: str | None = None


@dataclass(frozen=True, slots=True)
class UsbDeviceIdentity:
    usb_path: str
    vendor_id: str
    product_id: str
    serial: str | None = None
    physical_path: str | None = None


@dataclass(frozen=True, slots=True)
class NagaConnection:
    usb_path: str
    vendor_id: str
    product_id: str
    transport: Transport
    serial: str | None
    physical_path: str | None
    nodes: tuple[EventNode, ...]


def group_naga_nodes(
    candidates: Iterable[EventNode],
    usb_devices: Iterable[UsbDeviceIdentity] = (),
) -> tuple[NagaConnection, ...]:
    """Filter supported physical nodes and group siblings by USB device."""
    groups: dict[tuple[str, str], list[EventNode]] = {}
    identities: dict[tuple[str, str], UsbDeviceIdentity] = {}
    for identity in usb_devices:
        vendor_id = identity.vendor_id.lower()
        product_id = identity.product_id.lower()
        if vendor_id != VENDOR_ID or product_id not in PRODUCT_TRANSPORTS:
            continue
        key = (identity.usb_path, product_id)
        groups[key] = []
        identities[key] = identity

    for candidate in candidates:
        vendor_id = candidate.vendor_id.lower()
        product_id = candidate.product_id.lower()
        if vendor_id != VENDOR_ID or product_id not in PRODUCT_TRANSPORTS:
            continue
        if not candidate.usb_path or not candidate.interface_number:
            continue
        key = (candidate.usb_path, product_id)
        groups.setdefault(key, []).append(candidate)
        identities.setdefault(
            key,
            UsbDeviceIdentity(
                usb_path=candidate.usb_path,
                vendor_id=vendor_id,
                product_id=product_id,
                serial=candidate.serial,
                physical_path=candidate.physical_path,
            ),
        )

    connections: list[NagaConnection] = []
    for (usb_path, product_id), nodes in groups.items():
        ordered_nodes = tuple(
            sorted(nodes, key=lambda node: (node.interface_number, node.event_path))
        )
        identity = identities[(usb_path, product_id)]
        connections.append(
            NagaConnection(
                usb_path=usb_path,
                vendor_id=VENDOR_ID,
                product_id=product_id,
                transport=PRODUCT_TRANSPORTS[product_id],
                serial=identity.serial,
                physical_path=identity.physical_path,
                nodes=ordered_nodes,
            )
        )
    return tuple(
        sorted(connections, key=lambda connection: (connection.product_id, connection.usb_path))
    )


def discover_naga_connections(context: UdevContext | None = None) -> tuple[NagaConnection, ...]:
    """Return supported USB connections and their initialized event nodes."""
    context_factory = cast(_ContextFactory, import_module("pyudev").Context)
    active_context = context or context_factory()
    usb_devices = [
        identity
        for device in active_context.list_devices(subsystem="usb")
        if device.device_type == "usb_device" and (identity := _usb_identity(device)) is not None
    ]

    candidates: list[EventNode] = []
    for device in active_context.list_devices(subsystem="input"):
        if (candidate := _event_node(device)) is not None:
            candidates.append(candidate)

    return group_naga_nodes(candidates, usb_devices)


def resolve_event_node(device_number: int) -> EventNode:
    """Resolve an opened character-device descriptor back to current udev ancestry."""
    module = import_module("pyudev")
    context_factory = cast(_ContextFactory, module.Context)
    lookup = cast(_DeviceLookup, module.Devices)
    try:
        device = lookup.from_device_number(context_factory(), "char", device_number)
    except Exception as exc:
        raise OSError("could not resolve the opened input descriptor through udev") from exc
    event_node = _event_node(device)
    if event_node is None:
        raise OSError("opened descriptor is not a supported physical Naga event node")
    return event_node


def _event_node(device: UdevDevice) -> EventNode | None:
    event_path = device.device_node
    if not event_path or not device.sys_name.startswith("event") or not device.is_initialized:
        return None

    usb_device = device.find_parent("usb", "usb_device")
    usb_interface = device.find_parent("usb", "usb_interface")
    if usb_device is None or usb_interface is None:
        return None

    identity = _usb_identity(usb_device)
    interface_number = _text(usb_interface.attributes.get("bInterfaceNumber"))
    if identity is None or interface_number is None:
        return None

    return EventNode(
        event_path=event_path,
        usb_path=identity.usb_path,
        interface_number=interface_number.lower().zfill(2),
        vendor_id=identity.vendor_id,
        product_id=identity.product_id,
        serial=identity.serial,
        physical_path=identity.physical_path,
    )


def _usb_identity(device: UdevDevice) -> UsbDeviceIdentity | None:
    vendor_id = _text(device.attributes.get("idVendor"))
    product_id = _text(device.attributes.get("idProduct"))
    if vendor_id is None or product_id is None:
        return None
    vendor_id = vendor_id.lower().zfill(4)
    product_id = product_id.lower().zfill(4)
    if vendor_id != VENDOR_ID or product_id not in PRODUCT_TRANSPORTS:
        return None
    return UsbDeviceIdentity(
        usb_path=device.sys_path,
        vendor_id=vendor_id,
        product_id=product_id,
        serial=_property(device, "ID_SERIAL_SHORT") or _text(device.attributes.get("serial")),
        physical_path=_property(device, "ID_PATH"),
    )


def _property(device: UdevDevice, name: str) -> str | None:
    return _text(device.properties.get(name))


def _text(value: object) -> str | None:
    if isinstance(value, bytes):
        return value.decode("ascii", errors="replace")
    if isinstance(value, str):
        return value
    return None
