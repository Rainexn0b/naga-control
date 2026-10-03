"""OpenRazer implementation of the Naga hardware port."""

from collections.abc import Callable, Iterable
from importlib import import_module
from typing import Protocol, cast

from naga_control.adapters.openrazer.capabilities import (
    SCROLL_MODES,
    InvalidCapabilityResponseError,
    MissingCapabilityError,
    read_dpi_stages,
    read_hardware_state,
    read_scroll_modes,
)
from naga_control.adapters.openrazer.settings import apply_steps
from naga_control.domain.hardware import (
    HardwareIssue,
    HardwareIssueCode,
    HardwareScrollMode,
    HardwareState,
    HardwareStatus,
    HardwareTransport,
    SettingsFailure,
)
from naga_control.domain.profiles import Profile
from naga_control.ports.hardware import NagaTopology

_VENDOR_ID = 0x1532
_PRODUCT_IDS: dict[HardwareTransport, int] = {"wired": 0x00E7, "hyperspeed": 0x00E8}


class _ManagerSnapshot(Protocol):
    @property
    def devices(self) -> Iterable[object]: ...


type ManagerFactory = Callable[[], _ManagerSnapshot]


class _MutableClient(Protocol):
    dpi_stages: object
    scroll_mode: object


class _PrerequisiteError(Exception):
    pass


class OpenRazerBackend:
    """Select and operate one fresh OpenRazer client for the active transport."""

    def __init__(self, manager_factory: ManagerFactory | None = None) -> None:
        self._manager_factory = manager_factory or _default_manager_factory
        self._client: object | None = None
        self._connections: tuple[NagaTopology, ...] = ()
        self._state = HardwareState(status="absent", generation=0)

    @property
    def state(self) -> HardwareState:
        return self._state

    def rescan(self, connections: tuple[NagaTopology, ...]) -> HardwareState:
        self._connections = connections
        self.invalidate()
        generation = self._state.generation + 1
        if not connections:
            return self._set_clear("absent", generation)
        transports = {connection.transport for connection in connections}
        if {"wired", "hyperspeed"}.issubset(transports):
            return self._set_clear(
                "transport_conflict",
                generation,
                error=_issue(
                    "transport_conflict", "Wired and HyperSpeed transports are both attached."
                ),
            )
        if len(connections) > 1:
            return self._set_clear(
                "multiple_device_conflict",
                generation,
                error=_issue(
                    "multiple_device_conflict", "Multiple Naga devices use one transport."
                ),
            )
        connection = next(iter(connections))
        if not connection.nodes:
            return self._set_clear(
                "unavailable",
                generation,
                transport=connection.transport,
                error=_issue("input_nodes_unavailable", "The Naga input interfaces are not ready."),
            )
        expected_product = _PRODUCT_IDS.get(connection.transport)
        if (
            connection.vendor_id.lower() != "1532"
            or expected_product is None
            or connection.product_id.lower() != f"{expected_product:04x}"
        ):
            return self._set_clear(
                "unsupported",
                generation,
                error=_issue(
                    "matching_device_not_found",
                    "The physical device is not a supported Naga V3 Pro.",
                ),
            )
        try:
            manager = self._manager_factory()
            matches = [device for device in manager.devices if _matches(device, expected_product)]
        except _PrerequisiteError:
            return self._set_clear(
                "unavailable",
                generation,
                transport=connection.transport,
                error=_issue(
                    "prerequisite_unavailable",
                    "Compatible openrazer.client support is unavailable.",
                ),
            )
        except Exception:
            return self._set_clear(
                "unavailable",
                generation,
                transport=connection.transport,
                error=_issue("backend_unavailable", "OpenRazer is unavailable."),
            )
        if len(matches) != 1:
            code = "matching_device_not_found" if not matches else "ambiguous_matching_device"
            message = (
                "No matching OpenRazer Naga device was found."
                if not matches
                else "OpenRazer returned multiple matching Naga devices."
            )
            return self._set_clear("unsupported", generation, error=_issue(code, message))
        try:
            state = read_hardware_state(matches[0], generation, connection.transport)
        except MissingCapabilityError:
            return self._set_clear(
                "unsupported",
                generation,
                error=_issue(
                    "unsupported_capability", "OpenRazer lacks required Naga capabilities."
                ),
            )
        except InvalidCapabilityResponseError:
            return self._set_clear(
                "unsupported",
                generation,
                error=_issue(
                    "invalid_response", "OpenRazer returned invalid Naga capability data."
                ),
            )
        except Exception:
            return self._set_clear(
                "unavailable",
                generation,
                transport=connection.transport,
                error=_issue("device_unavailable", "The Naga device is unavailable."),
            )
        self._client = matches[0]
        self._state = state
        return state

    def refresh_state(self) -> HardwareState:
        """Re-read observed device state without mutating anything."""
        client = self._client_for_operation()
        if client is None:
            return self._state
        return self._refresh_after_operation(client)

    def move_dpi_stage(self, direction: int) -> HardwareState:
        if direction not in {-1, 1}:
            raise ValueError("direction must be -1 or 1")
        client = self._client_for_operation()
        if client is None:
            return self._state
        try:
            active, stages = read_dpi_stages(client)
            target = max(1, min(len(stages), active + direction))
            if target == active:
                return self._refresh_after_operation(client)
            cast(_MutableClient, client).dpi_stages = (
                target,
                tuple((stage.x, stage.y) for stage in stages),
            )
        except MissingCapabilityError:
            return self._operation_failure(
                "unsupported_capability", "OpenRazer lacks DPI stage control."
            )
        except InvalidCapabilityResponseError:
            return self._operation_failure(
                "invalid_response", "OpenRazer returned invalid DPI stages."
            )
        except Exception:
            return self._operation_failure("device_unavailable", "The Naga device is unavailable.")
        return self._refresh_after_operation(client)

    def set_scroll_mode(self, mode: HardwareScrollMode) -> HardwareState:
        if mode not in SCROLL_MODES:
            raise ValueError("mode must be a supported scroll mode")
        return self._change_scroll_mode(mode)

    def move_scroll_mode(self, direction: int) -> HardwareState:
        if direction not in {-1, 1}:
            raise ValueError("direction must be -1 or 1")
        client = self._client_for_operation()
        if client is None:
            return self._state
        try:
            mode, options = read_scroll_modes(client)
            ordered = tuple(candidate for candidate in SCROLL_MODES if candidate in options)
            target = ordered[(ordered.index(mode) + direction) % len(ordered)]
        except MissingCapabilityError:
            return self._operation_failure(
                "unsupported_capability", "OpenRazer lacks scroll mode control."
            )
        except InvalidCapabilityResponseError:
            return self._operation_failure(
                "invalid_response", "OpenRazer returned invalid scroll mode data."
            )
        return self._change_scroll_mode(cast(HardwareScrollMode, target), options=options)

    def apply_profile_settings(
        self, profile: Profile
    ) -> tuple[HardwareState, tuple[SettingsFailure, ...]]:
        """Write every desired setting in order and report partial failures."""
        client = self._client_for_operation()
        if client is None:
            return self._state, (SettingsFailure("profile", "hardware is not available"),)
        failures = apply_steps(client, profile)
        return self._refresh_after_operation(client), failures

    def invalidate(self) -> None:
        """Drop a client snapshot that may belong to a disconnected daemon/device."""
        self._client = None

    def close(self) -> None:
        self.invalidate()
        self._connections = ()

    def _change_scroll_mode(
        self, mode: HardwareScrollMode, *, options: tuple[HardwareScrollMode, ...] | None = None
    ) -> HardwareState:
        client = self._client_for_operation()
        if client is None:
            return self._state
        try:
            current, supported = read_scroll_modes(client)
            available = options or supported
            if mode not in available:
                return self._operation_failure(
                    "unsupported_capability", "The selected scroll mode is unavailable."
                )
            if mode == current:
                return self._refresh_after_operation(client)
            cast(_MutableClient, client).scroll_mode = SCROLL_MODES.index(mode)
        except MissingCapabilityError:
            return self._operation_failure(
                "unsupported_capability", "OpenRazer lacks scroll mode control."
            )
        except InvalidCapabilityResponseError:
            return self._operation_failure(
                "invalid_response", "OpenRazer returned invalid scroll mode data."
            )
        except Exception:
            return self._operation_failure("device_unavailable", "The Naga device is unavailable.")
        return self._refresh_after_operation(client)

    def _client_for_operation(self) -> object | None:
        if self._client is not None and self._state.status == "available":
            return self._client
        if self._state.status in {"available", "unavailable"} and self._connections:
            self.rescan(self._connections)
        if self._state.status == "available":
            return self._client
        return None

    def _refresh_after_operation(self, client: object) -> HardwareState:
        transport = self._state.transport
        if transport is None:
            return self._operation_failure("device_unavailable", "The Naga device is unavailable.")
        try:
            self._state = read_hardware_state(client, self._state.generation, transport)
        except MissingCapabilityError:
            return self._operation_failure(
                "unsupported_capability", "OpenRazer lacks required Naga capabilities."
            )
        except InvalidCapabilityResponseError:
            return self._operation_failure(
                "invalid_response", "OpenRazer returned invalid Naga capability data."
            )
        except Exception:
            return self._operation_failure("device_unavailable", "The Naga device is unavailable.")
        return self._state

    def _operation_failure(self, code: HardwareIssueCode, message: str) -> HardwareState:
        self.invalidate()
        status: HardwareStatus = (
            "unsupported"
            if code in {"unsupported_capability", "invalid_response"}
            else "unavailable"
        )
        return self._set_clear(
            status,
            self._state.generation,
            transport=self._state.transport,
            error=_issue(code, message),
        )

    def _set_clear(
        self,
        status: HardwareStatus,
        generation: int,
        *,
        transport: HardwareTransport | None = None,
        error: HardwareIssue | None = None,
    ) -> HardwareState:
        self._state = HardwareState(
            status=status,
            generation=generation,
            transport=transport,
            error=error,
        )
        return self._state


def _default_manager_factory() -> _ManagerSnapshot:
    try:
        module = import_module("openrazer.client")
        manager_class = module.DeviceManager
    except (ImportError, AttributeError) as exc:
        raise _PrerequisiteError from exc
    if not callable(manager_class):
        raise _PrerequisiteError
    return cast(_ManagerSnapshot, manager_class())


def _matches(device: object, expected_product: int) -> bool:
    try:
        vendor_id = object.__getattribute__(device, "_vid")
        product_id = object.__getattribute__(device, "_pid")
        return (
            isinstance(vendor_id, int)
            and not isinstance(vendor_id, bool)
            and isinstance(product_id, int)
            and not isinstance(product_id, bool)
            and vendor_id == _VENDOR_ID
            and product_id == expected_product
        )
    except AttributeError:
        return False


def _issue(code: HardwareIssueCode, message: str) -> HardwareIssue:
    return HardwareIssue(code=code, message=message)
