"""Read-only capture descriptors, identity validation, and ownership rollback."""

import os
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from importlib import import_module
from typing import Protocol, cast

from naga_control.adapters.evdev.discovery import EventNode, NagaConnection, resolve_event_node


class InputEventLike(Protocol):
    @property
    def sec(self) -> int: ...

    @property
    def usec(self) -> int: ...

    @property
    def type(self) -> int: ...

    @property
    def code(self) -> int: ...

    @property
    def value(self) -> int: ...


class AbsInfoLike(Protocol):
    @property
    def value(self) -> int: ...

    @property
    def min(self) -> int: ...

    @property
    def max(self) -> int: ...

    @property
    def fuzz(self) -> int: ...

    @property
    def flat(self) -> int: ...

    @property
    def resolution(self) -> int: ...


class DeviceInfoLike(Protocol):
    @property
    def bustype(self) -> int: ...

    @property
    def vendor(self) -> int: ...

    @property
    def product(self) -> int: ...

    @property
    def version(self) -> int: ...


class InputDeviceLike(Protocol):
    @property
    def fd(self) -> int: ...

    @property
    def name(self) -> str: ...

    @property
    def phys(self) -> str | None: ...

    @property
    def uniq(self) -> str | None: ...

    @property
    def info(self) -> DeviceInfoLike: ...

    def close(self) -> None: ...

    def input_props(self, verbose: bool = False) -> list[int]: ...

    def capabilities(
        self, verbose: bool = False, absinfo: bool = True
    ) -> Mapping[int, Sequence[int | tuple[int, AbsInfoLike]]]: ...

    def async_read_loop(self) -> AsyncIterator[InputEventLike]: ...


class InputDeviceFactory(Protocol):
    def __call__(self, path: str, readonly: bool = False) -> InputDeviceLike: ...


_input_device_factory = cast(InputDeviceFactory, import_module("evdev").InputDevice)


@dataclass(frozen=True, slots=True)
class OpenedSource:
    source_id: str
    node: EventNode
    device: InputDeviceLike


def open_sources(
    connection: NagaConnection,
    *,
    device_factory: InputDeviceFactory = _input_device_factory,
    identity_resolver: Callable[[int], EventNode] = resolve_event_node,
    device_number_resolver: Callable[[int], int] = lambda fd: os.fstat(fd).st_rdev,
) -> tuple[OpenedSource, ...]:
    """Open siblings read-only with stable identifiers and descriptor validation.

    Rollback preserves the primary failure against ordinary close errors only;
    a secondary interruption can replace it and interrupt remaining cleanup.
    """
    opened: list[OpenedSource] = []
    interface_counts: dict[str, int] = {}
    try:
        for node in connection.nodes:
            interface_counts[node.interface_number] = (
                interface_counts.get(node.interface_number, 0) + 1
            )
            occurrence = interface_counts[node.interface_number]
            source_id = f"interface-{node.interface_number}"
            if occurrence > 1:
                source_id = f"{source_id}-{occurrence}"
            device = device_factory(node.event_path, readonly=True)
            try:
                current_node = identity_resolver(device_number_resolver(device.fd))
                if not _same_physical_source(node, current_node):
                    raise OSError(f"input identity changed before open: {node.event_path}")
            except BaseException:
                with suppress(Exception):
                    device.close()
                raise
            opened.append(OpenedSource(source_id, node, device))
    except BaseException:
        with suppress(Exception):
            close_sources(opened)
        raise
    return tuple(opened)


def close_sources(sources: tuple[OpenedSource, ...] | list[OpenedSource]) -> None:
    """Attempt all closes after ordinary failures, then raise the first error.

    KeyboardInterrupt/SystemExit and other BaseException interruptions abort
    cleanup immediately; a failed close is an attempt, not proof of fd release.
    """
    first_error: Exception | None = None
    for source in sources:
        try:
            source.device.close()
        except Exception as exc:
            if first_error is None:
                first_error = exc
    if first_error is not None:
        raise first_error


def _same_physical_source(expected: EventNode, current: EventNode) -> bool:
    return (
        expected.usb_path == current.usb_path
        and expected.interface_number == current.interface_number
        and expected.vendor_id == current.vendor_id
        and expected.product_id == current.product_id
    )
