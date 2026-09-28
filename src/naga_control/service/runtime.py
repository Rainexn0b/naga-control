"""Lifecycle core for one active Naga transport and its remapping session."""

import logging
from collections.abc import Callable
from dataclasses import replace
from typing import Protocol

from naga_control.adapters.evdev.discovery import NagaConnection
from naga_control.config import dump_toml, parse_toml
from naga_control.domain.defaults import default_configuration
from naga_control.domain.hardware import HardwareState, SettingsFailure
from naga_control.domain.profiles import (
    Bindings,
    Configuration,
    DpiSettings,
    DpiStage,
    Profile,
    ScrollSettings,
)
from naga_control.ports.config_store import ConfigurationStore
from naga_control.ports.hardware import NagaTopology

logger = logging.getLogger(__name__)


class StaleConfigurationRevisionError(RuntimeError):
    """The caller applied a configuration that was not based on the current revision."""


class UnknownProfileError(ValueError):
    """The requested profile identifier does not exist."""


class ServiceHardwareWorker(Protocol):
    async def start(self) -> None: ...

    def mark_topology_stale(self) -> None: ...

    async def rescan(self, connections: tuple[NagaTopology, ...]) -> HardwareState: ...

    async def apply_profile_settings(
        self, profile: Profile
    ) -> tuple[HardwareState, tuple[SettingsFailure, ...]]: ...

    async def stop(self) -> None: ...


class RemappingSession(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    def release_all(self) -> None: ...


class NagaService:
    """Start mappings only for one discovered physical transport."""

    def __init__(
        self,
        discover: Callable[[], tuple[NagaConnection, ...]],
        load_configuration: Callable[[], Configuration | None],
        worker: ServiceHardwareWorker,
        session_factory: Callable[[NagaConnection, Configuration], RemappingSession],
        store: ConfigurationStore | None = None,
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

    async def start(self) -> HardwareState:
        if self._started:
            raise RuntimeError("Naga service is already active")
        self._started = True
        try:
            self._configuration = self._load_configuration() or default_configuration()
            await self._worker.start()
            return await self.apply_topology(self._discover())
        except BaseException:
            await self.stop()
            raise

    async def apply_topology(self, connections: tuple[NagaConnection, ...]) -> HardwareState:
        """Stop the current session and rebuild it for a fresh physical topology."""
        if not self._started or self._configuration is None:
            raise RuntimeError("Naga service is not active")
        session = self._session
        self._session = None
        if session is not None:
            await session.stop()
        state = await self.rescan(connections)
        if len(connections) == 1 and connections[0].nodes:
            self._session = self._session_factory(connections[0], self._session_configuration())
            await self._session.start()
        await self._apply_profile_settings()
        return state

    async def _apply_profile_settings(self) -> None:
        """Make the hardware reflect the desired profile, keeping partial failures.

        Skipped while calibrating so on-device adjustments are not overwritten.
        """
        assert self._configuration is not None
        if self._calibrating:
            return
        profile = self._configuration.profile(self._configuration.active_profile)
        state, failures = await self._worker.apply_profile_settings(profile)
        self._settings_failures = failures
        if state.status == "available":
            self._state = state
        for failure in failures:
            logger.warning("profile setting %s failed: %s", failure.setting, failure.message)

    def mark_topology_stale(self) -> None:
        """Fence device actions synchronously after an OpenRazer lifecycle signal."""
        if self._started:
            self._worker.mark_topology_stale()

    async def rescan(self, connections: tuple[NagaTopology, ...]) -> HardwareState:
        """Refresh OpenRazer clients without rebuilding physical input forwarding."""
        if not self._started:
            raise RuntimeError("Naga service is not active")
        state = await self._worker.rescan(connections)
        self._state = state
        return state

    def release_all(self) -> None:
        if self._session is not None:
            self._session.release_all()

    async def begin_calibration(self) -> bool:
        """Rebuild forwarding with passthrough bindings for direct device adjustments."""
        if not self._started:
            raise RuntimeError("Naga service is not active")
        self._calibrating = True
        await self.apply_topology(self._discover())
        return True

    async def end_calibration(self) -> bool:
        """Adopt observed DPI and scroll state, then resume normal mapping."""
        self._calibrating = False
        connections = self._discover()
        await self.rescan(connections)
        self._adopt_observed_settings()
        await self.apply_topology(connections)
        return False

    def _session_configuration(self) -> Configuration:
        configuration = self._require_configuration()
        if not self._calibrating:
            return configuration
        active = configuration.active_profile
        profiles = tuple(
            (
                identifier,
                replace(
                    profile,
                    bindings=Bindings(common=(), plate_2=(), plate_6=(), plate_12=()),
                ),
            )
            if identifier == active
            else (identifier, profile)
            for identifier, profile in configuration.profiles
        )
        return replace(configuration, profiles=profiles)

    def _adopt_observed_settings(self) -> None:
        state = self._state
        if state is None or state.status != "available":
            return
        mode = state.scroll_mode
        acceleration = state.scroll_acceleration
        smart_reel = state.scroll_smart_reel
        if not state.dpi_stages or mode is None or acceleration is None or smart_reel is None:
            return
        configuration = self._require_configuration()
        active = configuration.active_profile
        adopted_dpi = DpiSettings(
            stages=tuple(DpiStage(stage.x, stage.y) for stage in state.dpi_stages),
            active_stage=state.active_dpi_stage or 1,
        )
        adopted_scroll = ScrollSettings(mode=mode, acceleration=acceleration, smart_reel=smart_reel)
        profiles = tuple(
            (identifier, replace(profile, dpi=adopted_dpi, scroll=adopted_scroll))
            if identifier == active
            else (identifier, profile)
            for identifier, profile in configuration.profiles
        )
        self._store_configuration(
            replace(configuration, profiles=profiles, revision=configuration.revision + 1)
        )
        logger.info(
            "calibration adopted %d DPI stages (active %d) into profile %s",
            len(adopted_dpi.stages),
            adopted_dpi.active_stage,
            active,
        )

    def record_hardware_state(self, state: HardwareState) -> None:
        """Publish a completed device action without allowing stale state regression."""
        if self._started and (self._state is None or state.generation >= self._state.generation):
            self._state = state

    def configuration_document(self) -> str:
        return dump_toml(self._require_configuration())

    def configuration_revision(self) -> int:
        return self._require_configuration().revision

    async def apply_configuration(self, expected_revision: int, document: str) -> int:
        """Validate a complete replacement document and rebuild the session."""
        current = self._require_configuration()
        configuration = parse_toml(document)
        if expected_revision != current.revision or configuration.revision != current.revision + 1:
            raise StaleConfigurationRevisionError(
                f"expected base revision {current.revision}, got {expected_revision}"
            )
        self._store_configuration(configuration)
        await self.apply_topology(self._discover())
        return configuration.revision

    async def select_profile(self, profile_id: str) -> int:
        """Switch the active profile durably and rebuild the session."""
        current = self._require_configuration()
        if profile_id not in {identifier for identifier, _ in current.profiles}:
            raise UnknownProfileError(f"unknown profile {profile_id!r}")
        updated = replace(current, active_profile=profile_id, revision=current.revision + 1)
        self._store_configuration(updated)
        await self.apply_topology(self._discover())
        return updated.revision

    def snapshot(self) -> dict[str, object]:
        state = self._state
        return {
            "status": state.status if state is not None else "absent",
            "generation": state.generation if state is not None else 0,
            "transport": state.transport if state is not None else None,
            "error": state.error.message if state is not None and state.error is not None else None,
            "settings_failures": [
                f"{failure.setting}: {failure.message}" for failure in self._settings_failures
            ],
            "calibrating": self._calibrating,
            "observed": _observed(state),
        }

    async def stop(self) -> None:
        session = self._session
        self._session = None
        if session is not None:
            await session.stop()
        if self._started:
            self._started = False
            await self._worker.stop()

    def _require_configuration(self) -> Configuration:
        if self._configuration is None:
            raise RuntimeError("Naga service has no loaded configuration")
        return self._configuration

    def _store_configuration(self, configuration: Configuration) -> None:
        if self._store is not None:
            self._store.save(configuration)
        self._configuration = configuration


def _observed(state: HardwareState | None) -> dict[str, object]:
    if state is None or state.status != "available":
        return {}
    dpi = state.dpi
    return {
        "dpi": (dpi.x, dpi.y) if dpi is not None else None,
        "dpi_stage_count": len(state.dpi_stages),
        "active_dpi_stage": state.active_dpi_stage,
        "max_dpi": state.max_dpi,
        "scroll_mode": state.scroll_mode,
        "scroll_mode_options": list(state.scroll_mode_options),
        "scroll_acceleration": state.scroll_acceleration,
        "scroll_smart_reel": state.scroll_smart_reel,
        "poll_rate": state.poll_rate,
        "battery_percent": state.battery_percent,
        "charging": state.charging,
        "firmware_version": state.firmware_version,
    }
