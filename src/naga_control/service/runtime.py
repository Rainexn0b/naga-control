"""Lifecycle core for one active Naga transport and its remapping session."""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import replace

from naga_control.adapters.evdev.discovery import NagaConnection
from naga_control.config import dump_toml, parse_toml
from naga_control.domain.defaults import default_configuration
from naga_control.domain.hardware import DeviceMode, HardwareState, SettingsFailure
from naga_control.domain.profiles import Configuration
from naga_control.ports.config_store import ConfigurationStore
from naga_control.ports.hardware import NagaTopology
from naga_control.service.calibration import adopt_observed_settings, passthrough_configuration
from naga_control.service.contracts import RemappingSession, ServiceHardwareWorker
from naga_control.service.snapshot import snapshot_document

logger = logging.getLogger(__name__)


class StaleConfigurationRevisionError(RuntimeError):
    """The requested revision is no longer current."""


class UnknownProfileError(ValueError):
    """The requested profile does not exist."""


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
        self._load_configuration = load_configuration
        self._worker = worker
        self._session_factory = session_factory
        self._store = store
        self._session: RemappingSession | None = None
        self._state: HardwareState | None = None
        self._configuration: Configuration | None = None
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
        self._cleanup_tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> HardwareState:
        starting = False
        try:
            async with self._lock:
                if self._started:
                    raise RuntimeError("Naga service is already active")
                starting = True
                self._started = True
                self._configuration = self._load_configuration() or default_configuration()
                await self._worker.start()
                state = await self._apply_topology(self._discover())
                self._state_poll_task = asyncio.create_task(self._poll_observed_state())
                return state
        except BaseException:
            if starting:
                await self.stop()
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
                    if mode != self._require_configuration().mode:
                        self._mode_error = f"device mode drifted to {mode}"
                        await self._stop_session()
                        if (
                            self._require_configuration().mode == "firmware"
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
                        await self._stop_session()
                    elif (
                        self._session is None and mode == "software" and not self._mode_write_failed
                    ):
                        connections = self._discover()
                        if len(connections) == 1 and connections[0].nodes:
                            await self._apply_topology(connections)
                except Exception as exc:
                    self._observed_mode = None
                    self._mode_error = str(exc)
                    await self._stop_session()
                    logger.debug("periodic state refresh failed", exc_info=True)

    async def apply_topology(self, connections: tuple[NagaConnection, ...]) -> HardwareState:
        async with self._lock:
            return await self._apply_topology(connections)

    async def _stop_session(self) -> None:
        session, self._session = self._session, None
        if session is not None:
            self._worker.mark_topology_stale()
            self._needs_rescan = True
            await session.stop()

    async def _apply_topology(self, connections: tuple[NagaConnection, ...]) -> HardwareState:
        if not self._started or self._configuration is None:
            raise RuntimeError("Naga service is not active")
        await self._stop_session()
        state = await self._rescan(connections)
        if self._mode_ready() and self._configuration.mode == "software":
            await self._apply_profile_settings()
            if self._mode_ready() and len(connections) == 1 and connections[0].nodes:
                await self._start_session(connections[0])
        return state

    async def _start_session(self, connection: NagaConnection) -> None:
        configuration = self._require_configuration()
        if self._calibrating:
            configuration = passthrough_configuration(configuration)
        session = self._session_factory(connection, configuration)
        self._session = session
        try:
            await session.start()
        except BaseException as exc:
            self._session = None
            self._mode_error = f"input forwarding: {exc}"
            await session.stop()
            raise

    def _mode_ready(self) -> bool:
        return (
            self._state is not None
            and self._state.status == "available"
            and self._observed_mode == self._require_configuration().mode
        )

    async def _apply_profile_settings(self) -> None:
        assert self._configuration is not None
        if self._calibrating:
            return
        profile = self._configuration.profile(self._configuration.active_profile)
        state, failures = await self._worker.apply_profile_settings(profile)
        self._settings_failures = failures
        self._state = state
        if state.status != "available":
            self._observed_mode = None
            self._mode_error = "device mode unknown: profile settings lost hardware access"
            await self._stop_session()
        for failure in failures:
            logger.warning("profile setting %s failed: %s", failure.setting, failure.message)

    def mark_topology_stale(self) -> None:
        if self._started:
            self._worker.mark_topology_stale()
            self._topology_epoch += 1
            self._needs_rescan = True
            self._observed_mode = None
            self._mode_error = "OpenRazer topology changed"
            if session := self._session:
                try:
                    session.release_all()
                except Exception:
                    logger.exception("could not release generated outputs after topology change")
                self._schedule_stop(session)

    def _schedule_stop(self, session: RemappingSession) -> None:
        task = asyncio.create_task(self._stop_unsafe_session(session))
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_tasks.discard)

    async def _stop_unsafe_session(self, session: RemappingSession) -> None:
        try:
            async with self._lock:
                if self._session is session:
                    await self._stop_session()
        except Exception:
            logger.exception("could not stop unsafe remapping session")

    async def rescan(self, connections: tuple[NagaTopology, ...]) -> HardwareState:
        async with self._lock:
            await self._stop_session()
            state = await self._rescan(connections)
            if (
                self._mode_ready()
                and self._require_configuration().mode == "software"
                and self._session is None
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
        epoch = self._topology_epoch
        try:
            state = await self._worker.rescan(connections)
        except Exception as exc:
            self._observed_mode = None
            self._mode_error = f"device rescan: {exc}"
            await self._stop_session()
            raise
        self._state = state
        self._observed_mode = None
        self._mode_error = None
        self._mode_write_failed = False
        if epoch == self._topology_epoch:
            self._needs_rescan = False
        if state.status != "available":
            self._mode_error = "device mode unavailable: hardware is not available"
            await self._stop_session()
            return state
        desired = self._require_configuration().mode
        if desired == "firmware":
            await self._stop_session()
            self._settings_failures = ()
        try:
            observed = await self._worker.read_device_mode()
            self._observed_mode = observed
            if observed != desired:
                await self._stop_session()
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
            await self._stop_session()
        return state

    def release_all(self) -> None:
        if self._session is not None:
            self._session.release_all()

    async def begin_calibration(self) -> bool:
        async with self._lock:
            if not self._started:
                raise RuntimeError("Naga service is not active")
            if self._require_configuration().mode == "firmware":
                raise RuntimeError("calibration requires software mode")
            self._calibrating = True
            await self._apply_topology(self._discover())
            return True

    async def end_calibration(self) -> bool:
        async with self._lock:
            if self._require_configuration().mode == "firmware":
                raise RuntimeError("calibration requires software mode")
            self._calibrating = False
            connections = self._discover()
            await self._rescan(connections)
            if adopted := adopt_observed_settings(self._require_configuration(), self._state):
                self._store_configuration(adopted)
            await self._apply_topology(connections)
            return False

    def record_hardware_state(self, state: HardwareState) -> None:
        if (
            self._started
            and self._mode_ready()
            and self._require_configuration().mode == "software"
            and (self._state is None or state.generation >= self._state.generation)
        ):
            self._state = state
            if state.status != "available":
                self._worker.mark_topology_stale()
                self._needs_rescan = True
                self._observed_mode = None
                self._mode_error = "device action lost hardware access"
                if session := self._session:
                    try:
                        session.release_all()
                    except Exception:
                        logger.exception(
                            "could not release generated outputs after hardware failure"
                        )
                    self._schedule_stop(session)

    def configuration_document(self) -> str:
        return dump_toml(self._require_configuration())

    def configuration_revision(self) -> int:
        return self._require_configuration().revision

    async def apply_configuration(self, expected_revision: int, document: str) -> int:
        configuration = parse_toml(document)
        async with self._lock:
            current = self._require_configuration()
            if (
                expected_revision != current.revision
                or configuration.revision != current.revision + 1
            ):
                raise StaleConfigurationRevisionError(
                    f"expected base revision {current.revision}, got {expected_revision}"
                )
            self._store_configuration(configuration)
            await self._apply_topology(self._discover())
            return configuration.revision

    async def select_profile(self, profile_id: str) -> int:
        async with self._lock:
            current = self._require_configuration()
            if profile_id not in {identifier for identifier, _ in current.profiles}:
                raise UnknownProfileError(f"unknown profile {profile_id!r}")
            updated = replace(current, active_profile=profile_id, revision=current.revision + 1)
            self._store_configuration(updated)
            await self._apply_topology(self._discover())
            return updated.revision

    def snapshot(self) -> dict[str, object]:
        return snapshot_document(
            self._state,
            self._configuration,
            self._settings_failures,
            self._calibrating,
            self._observed_mode,
            self._mode_error,
            self._session is not None,
        )

    async def stop(self) -> None:
        poll_task, self._state_poll_task = self._state_poll_task, None
        if poll_task is not None:
            poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await poll_task
        async with self._lock:
            await self._stop_session()
            if self._started:
                self._started = False
                await self._worker.stop()
        if self._cleanup_tasks:
            await asyncio.gather(*tuple(self._cleanup_tasks))

    def _require_configuration(self) -> Configuration:
        if self._configuration is None:
            raise RuntimeError("Naga service has no loaded configuration")
        return self._configuration

    def _store_configuration(self, configuration: Configuration) -> None:
        if self._store is not None:
            self._store.save(configuration)
        self._configuration = configuration
