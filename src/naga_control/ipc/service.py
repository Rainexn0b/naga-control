"""Small session D-Bus surface for the first service slice."""

import asyncio
import json
from collections.abc import Callable, Coroutine, Mapping
from typing import Protocol

from dbus_next.errors import DBusError
from dbus_next.service import ServiceInterface, method

from naga_control.domain.errors import ConfigValidationError
from naga_control.service.runtime import StaleConfigurationRevisionError, UnknownProfileError

BUS_NAME = "org.nagacontrol.Service1"
OBJECT_PATH = "/org/nagacontrol/Service1"
INTERFACE_NAME = "org.nagacontrol.Service1"

_ERROR_PREFIX = "org.nagacontrol.Service1.Error"


class ServiceSnapshotProvider(Protocol):
    def snapshot(self) -> Mapping[str, object]: ...

    def release_all(self) -> None: ...


class ServiceConfigurationProvider(ServiceSnapshotProvider, Protocol):
    def configuration_document(self) -> str: ...

    def configuration_revision(self) -> int: ...

    async def apply_configuration(self, expected_revision: int, document: str) -> int: ...

    async def select_profile(self, profile_id: str) -> int: ...

    async def begin_calibration(self) -> bool: ...

    async def end_calibration(self) -> bool: ...


class NagaControlInterface(ServiceInterface):
    """Expose only safe service state and emergency generated-output release."""

    def __init__(self, service: ServiceConfigurationProvider, *, ready: bool = True) -> None:
        super().__init__(INTERFACE_NAME)
        self._service = service
        self._ready = asyncio.Event()
        self._unavailable = False
        self._shutdown_prepare: Callable[[], Coroutine[None, None, None]] | None = None
        self._shutdown_request_exit: Callable[[], None] | None = None
        self._prepare_succeeded = False
        self._prepare_task: asyncio.Task[None] | None = None
        self._shutdown_lock = asyncio.Lock()
        if ready:
            self._ready.set()

    def set_shutdown_callbacks(
        self,
        prepare: Callable[[], Coroutine[None, None, None]],
        request_exit: Callable[[], None],
    ) -> None:
        """Bind CLI-owned graceful-stop controls after construction.

        Kept as a setter so the existing constructor signature stays valid
        for tests that monkeypatch it. Interfaces without these callbacks
        reject the new shutdown methods with the fixed unavailable error.
        """
        self._shutdown_prepare = prepare
        self._shutdown_request_exit = request_exit

    def mark_ready(self) -> None:
        if not self._unavailable:
            self._ready.set()

    def mark_unavailable(self) -> None:
        self._unavailable = True
        self._ready.set()

    async def _wait_ready(self) -> None:
        await self._ready.wait()
        if self._unavailable:
            raise DBusError(
                f"{_ERROR_PREFIX}.Unavailable", "Naga Control service is unavailable."
            ) from None

    def _shutdown_unavailable(self) -> DBusError:
        return DBusError(f"{_ERROR_PREFIX}.Unavailable", "Naga Control service is unavailable.")

    async def _join_prepare_task(self, task: asyncio.Task[None]) -> None:
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise self._shutdown_unavailable() from None
        self._prepare_succeeded = True
        return None

    @method()
    async def GetSnapshot(  # pyright: ignore[reportUnknownParameterType]
        self,
    ) -> "s":  # noqa: F821  # pyright: ignore[reportUndefinedVariable, reportUnknownParameterType]
        await self._wait_ready()
        return self.snapshot_document()

    @method()
    async def ReleaseAll(self) -> None:
        await self._wait_ready()
        self.release_outputs()

    @method()
    async def GetConfiguration(  # pyright: ignore[reportUnknownParameterType]
        self,
    ) -> "s":  # noqa: F821  # pyright: ignore[reportUndefinedVariable, reportUnknownParameterType]
        await self._wait_ready()
        return self.configuration_document()

    @method()
    async def ApplyConfiguration(  # pyright: ignore[reportUnknownParameterType]
        self,
        expected_revision: "q",  # noqa: F821  # pyright: ignore[reportUndefinedVariable, reportUnknownParameterType]
        document: "s",  # noqa: F821  # pyright: ignore[reportUndefinedVariable, reportUnknownParameterType]
    ) -> "q":  # noqa: F821  # pyright: ignore[reportUndefinedVariable, reportUnknownParameterType]
        await self._wait_ready()
        return await self.apply_configuration(
            expected_revision,  # pyright: ignore[reportUnknownArgumentType]
            document,  # pyright: ignore[reportUnknownArgumentType]
        )

    @method()
    async def SelectProfile(  # pyright: ignore[reportUnknownParameterType]
        self,
        profile_id: "s",  # noqa: F821  # pyright: ignore[reportUndefinedVariable, reportUnknownParameterType]
    ) -> "q":  # noqa: F821  # pyright: ignore[reportUndefinedVariable, reportUnknownParameterType]
        await self._wait_ready()
        return await self.select_profile(
            profile_id,  # pyright: ignore[reportUnknownArgumentType]
        )

    @method()
    async def BeginCalibration(  # pyright: ignore[reportUnknownParameterType]
        self,
    ) -> "b":  # noqa: F821  # pyright: ignore[reportUndefinedVariable, reportUnknownParameterType]
        await self._wait_ready()
        return await self.begin_calibration_state()

    @method()
    async def EndCalibration(  # pyright: ignore[reportUnknownParameterType]
        self,
    ) -> "b":  # noqa: F821  # pyright: ignore[reportUndefinedVariable, reportUnknownParameterType]
        await self._wait_ready()
        return await self.end_calibration_state()

    @method()
    async def PrepareShutdown(self) -> None:
        """Close the readiness gate, stop resources, reply only when clean."""
        prepare = self._shutdown_prepare
        if prepare is None:
            raise self._shutdown_unavailable() from None
        if self._prepare_succeeded:
            return None
        existing = self._prepare_task
        if existing is not None:
            await self._join_prepare_task(existing)
            return None
        try:
            await self._wait_ready()
        except DBusError:
            if self._prepare_succeeded:
                return None
            pending = self._prepare_task
            if pending is not None:
                await self._join_prepare_task(pending)
                return None
            raise self._shutdown_unavailable() from None
        async with self._shutdown_lock:
            if self._prepare_succeeded:
                return None
            if self._prepare_task is not None:
                task: asyncio.Task[None] = self._prepare_task
            else:
                # Terminal gate close precedes resource cleanup so no new
                # application call can enter while owners are stopping.
                self.mark_unavailable()
                task = asyncio.create_task(prepare())
                self._prepare_task = task
        await self._join_prepare_task(task)
        return None

    @method()
    async def Exit(self) -> None:
        """Request CLI exit; permitted only after successful prepare."""
        if self._shutdown_request_exit is None:
            raise self._shutdown_unavailable() from None
        if not self._prepare_succeeded:
            raise self._shutdown_unavailable() from None
        self._shutdown_request_exit()
        return None

    def snapshot_document(self) -> str:
        return json.dumps(self._service.snapshot(), sort_keys=True, separators=(",", ":"))

    def release_outputs(self) -> None:
        self._service.release_all()

    async def begin_calibration_state(self) -> bool:
        return await self._service.begin_calibration()

    async def end_calibration_state(self) -> bool:
        return await self._service.end_calibration()

    def configuration_document(self) -> str:
        return self._service.configuration_document()

    async def apply_configuration(self, expected_revision: int, document: str) -> int:
        try:
            return await self._service.apply_configuration(expected_revision, document)
        except StaleConfigurationRevisionError as exc:
            raise DBusError(f"{_ERROR_PREFIX}.StaleRevision", str(exc)) from exc
        except ConfigValidationError as exc:
            raise DBusError(f"{_ERROR_PREFIX}.InvalidConfiguration", str(exc)) from exc

    async def select_profile(self, profile_id: str) -> int:
        try:
            return await self._service.select_profile(profile_id)
        except UnknownProfileError as exc:
            raise DBusError(f"{_ERROR_PREFIX}.UnknownProfile", str(exc)) from exc
