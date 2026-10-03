"""Synchronous port for serialized Naga hardware operations."""

from typing import Protocol

from naga_control.domain.hardware import (
    HardwareScrollMode,
    HardwareState,
    HardwareTransport,
    SettingsFailure,
)
from naga_control.domain.intents import DeviceActionIntent
from naga_control.domain.profiles import Profile


class DeviceActionSubmitter(Protocol):
    """Accept a device action without blocking the input frame callback."""

    def submit(self, intent: DeviceActionIntent) -> bool: ...


class NagaTopology(Protocol):
    """Physical topology required before selecting an OpenRazer device."""

    @property
    def vendor_id(self) -> str: ...

    @property
    def product_id(self) -> str: ...

    @property
    def transport(self) -> HardwareTransport: ...

    @property
    def nodes(self) -> tuple[object, ...]: ...


class PhysicalTopologyProvider(Protocol):
    """Provide the current physical Naga USB topology."""

    def get_topology(self) -> tuple[NagaTopology, ...]: ...


class HardwareTopologyRescanController(Protocol):
    """Fence mutations and refresh hardware clients after a lifecycle change."""

    def mark_topology_stale(self) -> None: ...

    async def rescan(self, connections: tuple[NagaTopology, ...]) -> HardwareState: ...


class HardwareBackend(Protocol):
    """Synchronous, thread-confined backend contract."""

    def rescan(self, connections: tuple[NagaTopology, ...]) -> HardwareState: ...

    def refresh_state(self) -> HardwareState: ...

    def move_dpi_stage(self, direction: int) -> HardwareState: ...

    def set_scroll_mode(self, mode: HardwareScrollMode) -> HardwareState: ...

    def move_scroll_mode(self, direction: int) -> HardwareState: ...

    def apply_profile_settings(
        self, profile: Profile
    ) -> tuple[HardwareState, tuple[SettingsFailure, ...]]: ...

    def invalidate(self) -> None: ...

    def close(self) -> None: ...
