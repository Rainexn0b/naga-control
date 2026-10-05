"""Opt-in, single-transport mode handoff using the real service and mouse.

Stop the installed service and quit the GUI first. Run only with a backup keyboard:
    .venv/bin/pytest -m hardware -s tests/hardware/test_mode_handoff.py
"""

import asyncio
import os
import subprocess
from dataclasses import replace
from importlib import import_module
from pathlib import Path
from time import monotonic
from typing import Protocol, cast

import pytest

from naga_control.adapters.config.storage import TomlConfigStore, default_config_path
from naga_control.adapters.evdev.discovery import discover_naga_connections
from naga_control.adapters.openrazer.backend import OpenRazerBackend
from naga_control.adapters.openrazer.lifecycle_monitor import OpenRazerLifecycleMonitor
from naga_control.application.service_factory import create_service
from naga_control.config import dump_toml, parse_toml
from naga_control.domain.hardware import DeviceMode
from naga_control.domain.profiles import Configuration
from naga_control.ports.hardware import NagaTopology
from naga_control.service.source_forwarding import SourceActivationError

pytestmark = pytest.mark.hardware


class _InputDevice(Protocol):
    def active_keys(self) -> list[int]: ...

    def grab(self) -> None: ...

    def ungrab(self) -> None: ...

    def close(self) -> None: ...


class _InputDeviceFactory(Protocol):
    def __call__(self, path: str) -> _InputDevice: ...


class _PhysicalTopology:
    def get_topology(self) -> tuple[NagaTopology, ...]:
        return discover_naga_connections()


def _config() -> Configuration:
    saved = TomlConfigStore(default_config_path(os.environ, Path.home())).load()
    if saved is None:
        pytest.skip("a saved user profile is required to avoid changing hardware defaults")
    return saved


def _released(paths: tuple[str, ...]) -> None:
    factory = cast(_InputDeviceFactory, import_module("evdev").InputDevice)
    for path in paths:
        device = factory(path)
        try:
            device.grab()
            device.ungrab()
        finally:
            device.close()


async def _wait_for_released_keys(paths: tuple[str, ...]) -> None:
    factory = cast(_InputDeviceFactory, import_module("evdev").InputDevice)
    for _ in range(30):
        devices = [factory(path) for path in paths]
        try:
            if not any(device.active_keys() for device in devices):
                return
        finally:
            for device in devices:
                device.close()
        await asyncio.sleep(0.1)
    pytest.fail("physical key remains held; release every mouse button before driver mode")


@pytest.mark.asyncio
async def test_firmware_driver_mode_handoff_and_restore() -> None:
    active = subprocess.run(
        ["systemctl", "--user", "is-active", "--quiet", "naga-control.service"],
        check=False,
    )
    if active.returncode == 0:
        pytest.skip("stop the installed Naga Control service before the hardware test")
    connections = discover_naga_connections()
    if len(connections) != 1 or not connections[0].nodes:
        pytest.skip("exactly one supported physical Naga transport is required")
    paths = tuple(node.event_path for node in connections[0].nodes)
    if not all(os.access(path, os.R_OK | os.W_OK) for path in paths):
        pytest.skip("physical input nodes are not writable by the current user")

    configuration = _config()
    backend = OpenRazerBackend()
    if backend.rescan(connections).status != "available":
        pytest.skip("OpenRazer has no available Naga on this transport")
    original: DeviceMode = backend.read_device_mode()
    backend.close()
    print(f"Testing {connections[0].transport}; original device mode: {original}", flush=True)

    service = create_service(load_configuration=lambda: configuration)
    started = False
    try:
        await _wait_for_released_keys(paths)
        await service.start()
        started = True
        assert service.snapshot()["mode_ready"] is True
        firmware = replace(configuration, mode="firmware", revision=configuration.revision + 1)
        print("Requesting onboard firmware mode", flush=True)
        await service.apply_configuration(configuration.revision, dump_toml(firmware))
        assert service.snapshot()["desired_mode"] == "firmware"
        assert service.snapshot()["observed_mode"] == "firmware"
        assert service.snapshot()["mode_ready"] is True
        _released(paths)
        print("Firmware readback confirmed and all physical grabs released", flush=True)

        software = replace(firmware, mode="software", revision=firmware.revision + 1)
        print("Returning to OpenRazer driver mode", flush=True)
        await _wait_for_released_keys(paths)
        try:
            await service.apply_configuration(firmware.revision, dump_toml(software))
        except SourceActivationError as exc:
            if "physical keys are held" not in str(exc):
                raise
            assert service.snapshot()["mode_ready"] is False
            _released(paths)
            print("Held-key gate stopped forwarding; waiting before retry", flush=True)
            await _wait_for_released_keys(paths)
            await asyncio.sleep(0.5)
            await service.apply_topology(discover_naga_connections())
        assert service.snapshot()["observed_mode"] == "software"
        assert service.snapshot()["mode_ready"] is True
        print("Driver mode and remapping session ready", flush=True)
    finally:
        try:
            try:
                current = parse_toml(service.configuration_document())
            except RuntimeError:
                current = None
            if started and current is not None and current.mode != original:
                restored = replace(current, mode=original, revision=current.revision + 1)
                await service.apply_configuration(current.revision, dump_toml(restored))
        finally:
            try:
                await service.stop()
            finally:
                # Do not rely on a failed service transition to restore the mouse.
                try:
                    backend.rescan(connections)
                    await asyncio.to_thread(backend.set_device_mode, original)
                finally:
                    backend.close()
                _released(paths)


@pytest.mark.asyncio
async def test_firmware_policy_survives_openrazer_daemon_restart() -> None:
    if (
        subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", "naga-control.service"],
            check=False,
        ).returncode
        == 0
    ):
        pytest.skip("stop the installed Naga Control service before the hardware test")
    connections = discover_naga_connections()
    if len(connections) != 1 or not connections[0].nodes:
        pytest.skip("exactly one supported physical Naga transport is required")
    paths = tuple(node.event_path for node in connections[0].nodes)
    backend = OpenRazerBackend()
    if backend.rescan(connections).status != "available":
        pytest.skip("OpenRazer has no available Naga on this transport")
    original = backend.read_device_mode()
    backend.close()

    configuration = replace(_config(), mode="firmware")
    service = create_service(load_configuration=lambda: configuration)
    monitor = OpenRazerLifecycleMonitor(_PhysicalTopology(), service)
    try:
        await service.start()
        assert service.snapshot()["mode_ready"] is True
        await monitor.start()
        deadline = monotonic() + 15
        while monotonic() < deadline:
            initial = service.snapshot()
            if cast(int, initial["generation"]) >= 2 and initial["mode_ready"] is True:
                break
            await asyncio.sleep(0.1)
        else:
            pytest.fail(f"initial lifecycle rescan did not settle: {service.snapshot()}")
        baseline = cast(int, service.snapshot()["generation"])
        print(
            f"Restarting OpenRazer with firmware requested on {connections[0].transport}",
            flush=True,
        )
        process = await asyncio.create_subprocess_exec(
            "systemctl", "--user", "restart", "openrazer-daemon.service"
        )
        assert await process.wait() == 0
        deadline = monotonic() + 45
        while monotonic() < deadline:
            snapshot = service.snapshot()
            if cast(int, snapshot["generation"]) > baseline and snapshot["mode_ready"] is True:
                break
            await asyncio.sleep(0.2)
        else:
            pytest.fail(f"firmware mode did not recover after daemon restart: {service.snapshot()}")
        assert service.snapshot()["observed_mode"] == "firmware"
        _released(paths)
        print("Firmware mode recovered with no remapping grabs", flush=True)
    finally:
        try:
            await monitor.stop()
        finally:
            try:
                await service.stop()
            finally:
                try:
                    backend.rescan(discover_naga_connections())
                    await asyncio.to_thread(backend.set_device_mode, original)
                finally:
                    backend.close()
                _released(paths)
