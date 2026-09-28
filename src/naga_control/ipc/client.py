"""Qt-free async client for the org.nagacontrol.Service1 contract."""

from typing import Protocol

from dbus_next.errors import DBusError

from naga_control.ipc.service import BUS_NAME, INTERFACE_NAME, OBJECT_PATH


class StaleRevisionError(RuntimeError):
    """The service configuration revision moved on before our apply."""


class InvalidConfigurationError(RuntimeError):
    """The service rejected a configuration document."""


class UnknownProfileError(RuntimeError):
    """The service does not know the requested profile."""


class ServiceCalls(Protocol):
    async def call_get_snapshot(self) -> str: ...

    async def call_release_all(self) -> None: ...

    async def call_get_configuration(self) -> str: ...

    async def call_apply_configuration(self, expected_revision: int, document: str) -> int: ...

    async def call_select_profile(self, profile_id: str) -> int: ...

    async def call_begin_calibration(self) -> bool: ...

    async def call_end_calibration(self) -> bool: ...


class _ErrorNames:
    STALE = f"{BUS_NAME}.Error.StaleRevision"
    INVALID = f"{BUS_NAME}.Error.InvalidConfiguration"
    UNKNOWN_PROFILE = f"{BUS_NAME}.Error.UnknownProfile"


class NagaControlClient:
    """Translate the raw D-Bus surface into typed results and errors."""

    def __init__(self, calls: ServiceCalls) -> None:
        self._calls = calls

    async def snapshot_document(self) -> str:
        return await self._calls.call_get_snapshot()

    async def release_all(self) -> None:
        await self._calls.call_release_all()

    async def begin_calibration(self) -> bool:
        return await self._calls.call_begin_calibration()

    async def end_calibration(self) -> bool:
        return await self._calls.call_end_calibration()

    async def configuration_document(self) -> str:
        return await self._calls.call_get_configuration()

    async def apply_configuration(self, expected_revision: int, document: str) -> int:
        try:
            return await self._calls.call_apply_configuration(expected_revision, document)
        except DBusError as exc:
            raise _translated(exc) from exc

    async def select_profile(self, profile_id: str) -> int:
        try:
            return await self._calls.call_select_profile(profile_id)
        except DBusError as exc:
            raise _translated(exc) from exc


def _translated(exc: DBusError) -> Exception:
    name = str(getattr(exc, "type", "") or getattr(exc, "name", "") or "")
    message = str(getattr(exc, "text", "") or exc.reply or exc)
    if name == _ErrorNames.STALE:
        return StaleRevisionError(message)
    if name == _ErrorNames.INVALID:
        return InvalidConfigurationError(message)
    if name == _ErrorNames.UNKNOWN_PROFILE:
        return UnknownProfileError(message)
    return exc


class ServiceProxyObject(Protocol):
    def get_interface(self, name: str) -> ServiceCalls: ...


class IntrospectableBus(Protocol):
    async def introspect(self, name: str, path: str) -> object: ...

    def get_proxy_object(
        self, name: str, path: str, introspection: object
    ) -> ServiceProxyObject: ...


async def connect_service_client(bus: IntrospectableBus) -> NagaControlClient:
    """Build the typed client from an introspected proxy object."""
    introspection = await bus.introspect(BUS_NAME, OBJECT_PATH)
    proxy = bus.get_proxy_object(BUS_NAME, OBJECT_PATH, introspection)
    return NagaControlClient(proxy.get_interface(INTERFACE_NAME))
