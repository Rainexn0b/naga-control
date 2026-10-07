"""Debounced OpenRazer lifecycle monitoring over the session D-Bus."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from importlib import import_module
from typing import Protocol, cast

from naga_control.ports.hardware import (
    HardwareTopologyRescanController,
    PhysicalTopologyProvider,
)

logger = logging.getLogger(__name__)

DEVICE_ADDED_RULE = (
    "type='signal',sender='org.razer',path='/org/razer',interface='razer.devices',"
    "member='device_added'"
)
DEVICE_REMOVED_RULE = (
    "type='signal',sender='org.razer',path='/org/razer',interface='razer.devices',"
    "member='device_removed'"
)
NAME_OWNER_CHANGED_RULE = (
    "type='signal',sender='org.freedesktop.DBus',path='/org/freedesktop/DBus',"
    "interface='org.freedesktop.DBus',member='NameOwnerChanged',arg0='org.razer'"
)
_MATCH_RULES = (DEVICE_ADDED_RULE, DEVICE_REMOVED_RULE, NAME_OWNER_CHANGED_RULE)

type MessageHandler = Callable[[object], bool]
type BusFactory = Callable[[], Awaitable["LifecycleBus"]]


class LifecycleBus(Protocol):
    """The small D-Bus surface needed by the lifecycle monitor."""

    async def add_match(self, rule: str) -> None: ...

    async def remove_match(self, rule: str) -> None: ...

    def add_message_handler(self, handler: MessageHandler) -> None: ...

    def remove_message_handler(self, handler: MessageHandler) -> None: ...

    def disconnect(self) -> None: ...


class _RawBus(Protocol):
    async def call(self, message: object) -> object: ...

    def add_message_handler(self, handler: MessageHandler) -> None: ...

    def remove_message_handler(self, handler: MessageHandler) -> None: ...

    def disconnect(self) -> None: ...


class _ConnectableBus(Protocol):
    async def connect(self) -> _RawBus: ...


class _BusType(Protocol):
    SESSION: object


class _DbusNextLifecycleBus:
    """Translate the injected monitor bus port to dbus-next's low-level API."""

    def __init__(self, bus: _RawBus, message_factory: Callable[..., object]) -> None:
        self._bus = bus
        self._message_factory = message_factory

    async def add_match(self, rule: str) -> None:
        await self._call_match_method("AddMatch", rule)

    async def remove_match(self, rule: str) -> None:
        await self._call_match_method("RemoveMatch", rule)

    def add_message_handler(self, handler: MessageHandler) -> None:
        self._bus.add_message_handler(handler)

    def remove_message_handler(self, handler: MessageHandler) -> None:
        self._bus.remove_message_handler(handler)

    def disconnect(self) -> None:
        self._bus.disconnect()

    async def _call_match_method(self, member: str, rule: str) -> None:
        reply = await self._bus.call(
            self._message_factory(
                destination="org.freedesktop.DBus",
                path="/org/freedesktop/DBus",
                interface="org.freedesktop.DBus",
                member=member,
                signature="s",
                body=[rule],
            )
        )
        if _is_error_reply(reply):
            raise RuntimeError(f"D-Bus {member} failed")


class OpenRazerLifecycleMonitor:
    """Schedule topology refreshes without doing hardware work in D-Bus callbacks."""

    def __init__(
        self,
        topology_provider: PhysicalTopologyProvider,
        rescan_controller: HardwareTopologyRescanController,
        *,
        bus_factory: BusFactory | None = None,
        debounce_seconds: float = 0.25,
    ) -> None:
        if debounce_seconds < 0:
            raise ValueError("debounce_seconds must not be negative")
        self._topology_provider = topology_provider
        self._rescan_controller = rescan_controller
        self._bus_factory = bus_factory or _default_bus_factory
        self._debounce_seconds = debounce_seconds
        self._bus: LifecycleBus | None = None
        self._runner: asyncio.Task[None] | None = None
        self._subscribed_rules: list[str] = []
        self._handler_added = False
        self._rescan_requested = False
        self._stopping = False
        self._reported_rescan_failures: set[tuple[str, type[Exception]]] = set()

    async def start(self) -> None:
        if self._bus is not None:
            return
        if self._stopping:
            raise RuntimeError("OpenRazer lifecycle monitor is stopped")
        bus = await self._bus_factory()
        self._bus = bus
        try:
            bus.add_message_handler(self._handle_message)
            self._handler_added = True
            for rule in _MATCH_RULES:
                await bus.add_match(rule)
                self._subscribed_rules.append(rule)
        except Exception:
            await self._detach_bus()
            raise
        self._request_rescan()

    async def stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        runner = self._runner
        if runner is not None:
            runner.cancel()
            with suppress(asyncio.CancelledError):
                await runner
        self._runner = None
        await self._detach_bus()

    def _handle_message(self, message: object) -> bool:
        if not self._stopping and (_is_device_signal(message) or _is_owner_change(message)):
            self._request_rescan()
        return False

    def _request_rescan(self) -> None:
        self._rescan_controller.mark_topology_stale()
        self._rescan_requested = True
        if self._runner is None or self._runner.done():
            self._runner = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while self._rescan_requested and not self._stopping:
            await asyncio.sleep(self._debounce_seconds)
            self._rescan_requested = False
            phase = "topology discovery"
            try:
                topology = await asyncio.to_thread(self._topology_provider.get_topology)
                phase = "controller rescan"
                await self._rescan_controller.rescan(topology)
            except Exception as exc:
                failure = (phase, type(exc))
                if failure not in self._reported_rescan_failures:
                    # Exception payloads and tracebacks can expose device identifiers.
                    logger.warning(
                        "OpenRazer lifecycle rescan failed during %s (%s)",
                        phase,
                        type(exc).__name__,
                    )
                    self._reported_rescan_failures.add(failure)
            else:
                self._reported_rescan_failures.clear()

    async def _detach_bus(self) -> None:
        bus = self._bus
        if bus is None:
            return
        self._bus = None
        if self._handler_added:
            self._handler_added = False
            with suppress(Exception):
                bus.remove_message_handler(self._handle_message)
        for rule in reversed(self._subscribed_rules):
            with suppress(Exception):
                await bus.remove_match(rule)
        self._subscribed_rules.clear()
        with suppress(Exception):
            bus.disconnect()


async def _default_bus_factory() -> LifecycleBus:
    aio_module = import_module("dbus_next.aio")
    dbus_module = import_module("dbus_next")
    bus_class = cast(Callable[..., _ConnectableBus], aio_module.MessageBus)
    bus_type = cast(_BusType, dbus_module.BusType)
    message_factory = cast(Callable[..., object], dbus_module.Message)
    return _DbusNextLifecycleBus(
        await bus_class(bus_type=bus_type.SESSION).connect(), message_factory
    )


def _is_device_signal(message: object) -> bool:
    return (
        _message_text(message, "path") == "/org/razer"
        and _message_text(message, "interface") == "razer.devices"
        and _message_text(message, "member") in {"device_added", "device_removed"}
    )


def _is_owner_change(message: object) -> bool:
    body = cast(object, getattr(message, "body", None))
    if not isinstance(body, (list, tuple)) or not body:
        return False
    name = cast(object, body[0])
    if not isinstance(name, str):
        return False
    return (
        _message_text(message, "path") == "/org/freedesktop/DBus"
        and _message_text(message, "interface") == "org.freedesktop.DBus"
        and _message_text(message, "member") == "NameOwnerChanged"
        and name == "org.razer"
    )


def _message_text(message: object, attribute: str) -> str | None:
    value = getattr(message, attribute, None)
    return value if isinstance(value, str) else None


def _is_error_reply(message: object) -> bool:
    message_type = cast(object, getattr(message, "message_type", None))
    name = cast(object, getattr(message_type, "name", None))
    return message_type == "ERROR" or name == "ERROR"
