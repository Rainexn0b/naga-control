"""Concrete composition for the first-slice user service."""

import os
from collections.abc import Callable, Mapping
from pathlib import Path

from naga_control.adapters.config.storage import TomlConfigStore, default_config_path
from naga_control.adapters.evdev.discovery import NagaConnection, discover_naga_connections
from naga_control.adapters.evdev.source import open_evdev_source
from naga_control.adapters.openrazer.backend import OpenRazerBackend
from naga_control.adapters.uinput.keyboard import create_virtual_keyboard
from naga_control.adapters.uinput.mouse import create_virtual_mouse
from naga_control.adapters.uinput.proxy import UInputForwardingProxyFactory
from naga_control.adapters.uinput.readiness import create_proxy_readiness_waiter
from naga_control.application.remapping import FirstSliceSession
from naga_control.domain.hardware import HardwareState
from naga_control.domain.profiles import Configuration
from naga_control.service.device_action_executor import DeviceActionExecutor
from naga_control.service.hardware_worker import HardwareWorker
from naga_control.service.runtime import NagaService


def create_service(
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    discover: Callable[[], tuple[NagaConnection, ...]] = discover_naga_connections,
    load_configuration: Callable[[], Configuration | None] | None = None,
    worker: HardwareWorker | None = None,
    session_factory: Callable[[NagaConnection, Configuration], FirstSliceSession] | None = None,
) -> NagaService:
    """Assemble lazy adapters; opening input and uinput happens only on start."""
    active_worker = worker or HardwareWorker(OpenRazerBackend())
    service: NagaService | None = None

    def record_hardware_state(state: HardwareState) -> None:
        if service is not None:
            service.record_hardware_state(state)

    if load_configuration is None:
        store = TomlConfigStore(default_config_path(environ or os.environ, home or Path.home()))
        config_loader: Callable[[], Configuration | None] = store.load
    else:
        store = None
        config_loader = load_configuration
    service = NagaService(
        discover,
        config_loader,
        active_worker,
        session_factory or create_session_factory(active_worker, record_hardware_state),
        store,
    )
    return service


def create_session_factory(
    worker: HardwareWorker,
    on_state: Callable[[HardwareState], None] | None = None,
) -> Callable[[NagaConnection, Configuration], FirstSliceSession]:
    def create(connection: NagaConnection, configuration: Configuration) -> FirstSliceSession:
        return FirstSliceSession(
            connection,
            configuration.profile(configuration.active_profile),
            create_virtual_keyboard(),
            create_virtual_mouse(),
            DeviceActionExecutor(worker, on_state=on_state),
            open_evdev_source,
            UInputForwardingProxyFactory(),
            create_proxy_readiness_waiter(),
        )

    return create
