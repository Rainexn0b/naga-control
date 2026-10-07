"""Lifecycle core for one active Naga transport and its remapping session."""

import asyncio
import contextlib
import logging
from collections.abc import Callable

from naga_control.adapters.evdev.discovery import NagaConnection
from naga_control.domain.hardware import DeviceMode, HardwareState, SettingsFailure
from naga_control.domain.profiles import Configuration
from naga_control.ports.config_store import ConfigurationStore
from naga_control.ports.hardware import NagaTopology
from naga_control.service.calibration import adopt_observed_settings, passthrough_configuration
from naga_control.service.configuration_authority import ConfigurationAuthority
from naga_control.service.configuration_authority import (
    StaleConfigurationRevisionError as StaleConfigurationRevisionError,
)
from naga_control.service.configuration_authority import UnknownProfileError as UnknownProfileError
from naga_control.service.contracts import RemappingSession, ServiceHardwareWorker
from naga_control.service.session_lifecycle import SessionLifecycle
from naga_control.service.snapshot import snapshot_document

logger = logging.getLogger(__name__)


class NagaService:
    def __init__(
        self,
        discover: Callable[[], tuple[NagaConnection, ...]],
        load_configuration: Callable[[], Configuration | None],
        worker: ServiceHardwareWorker,
        session_factory: Callable[[NagaConnection, Configuration], RemappingSession],
        store: ConfigurationStore | None = None,
        state_poll_interval: float = 30.0,
    ) -> None:
        self._discover = discover
        self._config = ConfigurationAuthority(load_configuration, store)
        self._worker = worker
        self._session_factory = session_factory
        self._state: HardwareState | None = None
        self._settings_failures: tuple[SettingsFailure, ...] = ()
        self._started = False
        self._calibrating = False
        self._state_poll_task: asyncio.Task[None] | None = None
        self._state_poll_interval = state_poll_interval
        self._lock = asyncio.Lock()
        self._observed_mode: DeviceMode | None = None
        self._mode_error: str | None = None
        self._mode_write_failed = False
        self._needs_rescan = False
        self._topology_epoch = 0
        self._sessions = SessionLifecycle(self._fence_session)
        self._stop_task: asyncio.Task[Exception | None] | None = None
        self._cleanup_tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> HardwareState:
        starting = False
        try:
            async with self._lock:
                if self._stop_task is not None:
                    raise RuntimeError("Naga service has been stopped")
                if self._started:
                    raise RuntimeError("Naga service is already active")
                starting = True
                self._started = True
                self._config.load()
                await self._worker.start()
                state = await self._apply_topology(self._discover())
                if self._stop_task is not None:
                    raise RuntimeError("Naga service is stopping")
                self._state_poll_task = asyncio.create_task(self._poll_observed_state())
                return state
        except BaseException:
            if starting:
                try:
                    await self.stop()
                except Exception as exc:
                    logger.error("service startup rollback cleanup failed: %s", type(exc).__name__)
            raise

    async def _poll_observed_state(self) -> None:
        while True:
            await asyncio.sleep(self._state_poll_interval)
            async with self._lock:
                state = self._state
                if state is None or state.status == "absent":
                    continue
                if self._needs_rescan or state.status == "unavailable":
                    if self._needs_rescan or not self._mode_write_failed:
                        try:
                            await self._apply_topology(self._discover())
                        except Exception:
                            logger.debug("periodic topology recovery failed", exc_info=True)
                    continue
                if state.status != "available":
                    continue
                try:
                    mode = await self._worker.read_device_mode()
                    self._observed_mode = mode
                    if mode != self._config.require_current().mode:
                        self._mode_error = f"device mode drifted to {mode}"
                        await self._sessions.stop()
                        if (
                            self._config.require_current().mode == "firmware"
                            and not self._mode_write_failed
                        ):
                            try:
                                self._observed_mode = await self._worker.set_device_mode("firmware")
                                if self._observed_mode != "firmware":
                                    raise RuntimeError("device mode write did not verify")
                                self._mode_error = None
                            except Exception as exc:
                                self._observed_mode = None
                                self._mode_write_failed = True
                                self._mode_error = f"device mode: {exc}"
                        elif not self._mode_write_failed:
                            await self._apply_topology(self._discover())
                        continue
                    self._mode_error = None
                    self._state = await self._worker.refresh_state()
                    if self._state.status != "available":
                        await self._sessions.stop()
                    elif (
                        self._sessions.current is None
                        and mode == "software"
                        and not self._mode_write_failed
                    ):
                        connections = self._discover()
                        if len(connections) == 1 and connections[0].nodes:
                            await self._apply_topology(connections)
                except Exception as exc:
                    self._observed_mode = None
                    self._mode_error = str(exc)
                    await self._sessions.stop()
                    logger.debug("periodic state refresh failed", exc_info=True)

    async def apply_topology(self, connections: tuple[NagaConnection, ...]) -> HardwareState:
        async with self._lock:
            return await self._apply_topology(connections)

    def _fence_session(self) -> None:
        self._worker.mark_topology_stale()
        self._needs_rescan = True

    async def _require_mutable(self) -> None:
        if self._stop_task is not None or not self._started:
            raise RuntimeError("Naga service is not active")
        await self._sessions.wait()
        if self._stop_task is not None:
            raise RuntimeError("Naga service is stopping")

    async def _apply_topology(self, connections: tuple[NagaConnection, ...]) -> HardwareState:
        await self._require_mutable()
        await self._sessions.stop()
        state = await self._rescan(connections)
        if self._mode_ready() and self._config.require_current().mode == "software":
            await self._apply_profile_settings()
            if self._mode_ready() and len(connections) == 1 and connections[0].nodes:
                await self._start_session(connections[0])
        return state

    async def _start_session(self, connection: NagaConnection) -> None:
        await self._sessions.wait()
        configuration = self._config.require_current()
        if self._calibrating:
            configuration = passthrough_configuration(configuration)
        session = self._session_factory(connection, configuration)
        try:
            await self._sessions.start(session)
        except BaseException as exc:
            self._mode_error = f"input forwarding: {exc}"
            raise

    def _mode_ready(self) -> bool:
        return (
            not self._sessions.unsafe
            and self._state is not None
            and self._state.status == "available"
            and self._observed_mode == self._config.require_current().mode
        )

    async def _apply_profile_settings(self) -> None:
        await self._sessions.wait()
        configuration = self._config.current
        assert configuration is not None
        if self._calibrating:
            return
        profile = configuration.profile(configuration.active_profile)
        state, failures = await self._worker.apply_profile_settings(profile)
        self._settings_failures = failures
        self._state = state
        if state.status != "available":
            self._observed_mode = None
            self._mode_error = "device mode unknown: profile settings lost hardware access"
            await self._sessions.stop()
        for failure in failures:
            logger.warning("profile setting %s failed: %s", failure.setting, failure.message)

    def mark_topology_stale(self) -> None:
        if self._started:
            self._fence_session()
            self._topology_epoch += 1
            self._observed_mode = None
            self._mode_error = "OpenRazer topology changed"
            self._schedule_stop()

    def _schedule_stop(self) -> None:
        if task := self._sessions.invalidate(self._lock):
            self._cleanup_tasks.add(task)
            task.add_done_callback(self._cleanup_tasks.discard)

    async def rescan(self, connections: tuple[NagaTopology, ...]) -> HardwareState:
        async with self._lock:
            await self._require_mutable()
            await self._sessions.stop()
            state = await self._rescan(connections)
            if (
                self._mode_ready()
                and self._config.require_current().mode == "software"
                and self._sessions.current is None
            ):
                physical = self._discover()
                if len(physical) == 1 and physical[0].nodes:
                    await self._apply_profile_settings()
                    if self._mode_ready():
                        await self._start_session(physical[0])
            return state

    async def _rescan(self, connections: tuple[NagaTopology, ...]) -> HardwareState:
        if not self._started:
            raise RuntimeError("Naga service is not active")
        await self._sessions.wait()
        epoch = self._topology_epoch
        try:
            state = await self._worker.rescan(connections)
        except Exception as exc:
            self._observed_mode = None
            self._mode_error = f"device rescan: {exc}"
            await self._sessions.stop()
            raise
        self._state = state
        self._observed_mode = None
        self._mode_error = None
        self._mode_write_failed = False
        if epoch == self._topology_epoch:
            self._needs_rescan = False
        if state.status != "available":
            self._mode_error = "device mode unavailable: hardware is not available"
            await self._sessions.stop()
            return state
        desired = self._config.require_current().mode
        await self._sessions.wait()
        if desired == "firmware":
            await self._sessions.stop()
            self._settings_failures = ()
        try:
            observed = await self._worker.read_device_mode()
            self._observed_mode = observed
            if observed != desired:
                await self._sessions.stop()
                try:
                    self._observed_mode = await self._worker.set_device_mode(desired)
                except Exception:
                    self._mode_write_failed = True
                    raise
                if self._observed_mode != desired:
                    raise RuntimeError("device mode write did not verify")
        except Exception as exc:
            self._observed_mode = None
            self._mode_error = f"device mode: {exc}"
            await self._sessions.stop()
        return state

    def release_all(self) -> None:
        self._sessions.release_all()

    async def begin_calibration(self) -> bool:
        async with self._lock:
            await self._require_mutable()
            if self._config.require_current().mode == "firmware":
                raise RuntimeError("calibration requires software mode")
            self._calibrating = True
            await self._apply_topology(self._discover())
            return True

    async def end_calibration(self) -> bool:
        async with self._lock:
            await self._require_mutable()
            if self._config.require_current().mode == "firmware":
                raise RuntimeError("calibration requires software mode")
            self._calibrating = False
            connections = self._discover()
            await self._rescan(connections)
            if adopted := adopt_observed_settings(self._config.require_current(), self._state):
                self._config.save(adopted)
            await self._apply_topology(connections)
            return False

    def record_hardware_state(self, state: HardwareState) -> None:
        if (
            self._started
            and self._mode_ready()
            and self._config.require_current().mode == "software"
            and (self._state is None or state.generation >= self._state.generation)
        ):
            self._state = state
            if state.status != "available":
                self._fence_session()
                self._observed_mode = None
                self._mode_error = "device action lost hardware access"
                self._schedule_stop()

    def configuration_document(self) -> str:
        return self._config.document()

    def configuration_revision(self) -> int:
        return self._config.revision()

    async def apply_configuration(self, expected_revision: int, document: str) -> int:
        configuration = self._config.parse(document)
        async with self._lock:
            self._config.validate_revision(expected_revision, configuration)
            await self._require_mutable()
            revision = self._config.apply(expected_revision, configuration)
            await self._apply_topology(self._discover())
            return revision

    async def select_profile(self, profile_id: str) -> int:
        async with self._lock:
            await self._require_mutable()
            revision = self._config.select_profile(profile_id)
            await self._apply_topology(self._discover())
            return revision

    def snapshot(self) -> dict[str, object]:
        return snapshot_document(
            self._state,
            self._config.current,
            self._settings_failures,
            self._calibrating,
            self._observed_mode,
            self._mode_error,
            self._sessions.current is not None,
        )

    async def stop(self) -> None:
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._shutdown())
        elif self._stop_task.done():
            return
        if error := await asyncio.shield(self._stop_task):
            raise error

    async def _shutdown(self) -> Exception | None:
        error: Exception | None = None
        poll_task, self._state_poll_task = self._state_poll_task, None
        if poll_task is not None:
            poll_task.cancel()
            try:
                with contextlib.suppress(asyncio.CancelledError):
                    await poll_task
            except Exception as exc:
                error = exc
        async with self._lock:
            try:
                await self._sessions.stop()
            except Exception as exc:
                error = error or exc
            self._started = False
            try:
                await self._worker.stop()
            except Exception as exc:
                error = error or exc
        if self._cleanup_tasks:
            results = await asyncio.gather(*tuple(self._cleanup_tasks), return_exceptions=True)
            error = error or next((item for item in results if isinstance(item, Exception)), None)
        return error
