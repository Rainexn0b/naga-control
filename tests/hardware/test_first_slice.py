"""Opt-in hardware validation of the first remapping slice.

Runs the real service composition against exactly one attached wired or
HyperSpeed Naga with the 12-button plate. Never part of the default suite. Execute with:

    .venv/bin/pytest -m hardware -s tests/hardware/test_first_slice.py

Press script (each step has its own generous window; pace does not matter):

    1. press F13 (front left-edge / DPI up) once
    2. press F14 (rear left-edge / DPI down) once
    3. hold F17 (ring-finger / Hypershift) about one second, then release
"""

import asyncio
import json
import logging
import os
import platform
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from time import monotonic
from typing import Any, Protocol, cast

import pytest

from naga_control.adapters.evdev.discovery import discover_naga_connections
from naga_control.adapters.openrazer.backend import OpenRazerBackend
from naga_control.application.service_factory import create_session_factory
from naga_control.domain.defaults import default_configuration
from naga_control.service.hardware_worker import HardwareWorker
from naga_control.service.runtime import NagaService

pytestmark = pytest.mark.hardware

PRESS_WINDOW_SECONDS = float(os.environ.get("NAGA_HARDWARE_PRESS_WINDOW", "45"))
VIRTUAL_KEYBOARD_NAME = "Naga Control Virtual Keyboard"
REPORT_PATH = Path("hardware-captures/first-slice-validation.json")
EV_KEY = 1
EV_SYN = 0
SYN_REPORT = 0
KEY_LEFTALT = 56


class _InputEvent(Protocol):
    @property
    def type(self) -> int: ...

    @property
    def code(self) -> int: ...

    @property
    def value(self) -> int: ...


class _InputDevice(Protocol):
    @property
    def name(self) -> str: ...

    def grab(self) -> None: ...

    def ungrab(self) -> None: ...

    def close(self) -> None: ...

    def async_read_loop(self) -> AsyncIterator[_InputEvent]: ...


class _InputDeviceFactory(Protocol):
    def __call__(self, path: str, readonly: bool = False) -> _InputDevice: ...


class _Util(Protocol):
    def list_devices(self) -> list[str]: ...


def _input_device_factory() -> _InputDeviceFactory:
    return cast(_InputDeviceFactory, import_module("evdev").InputDevice)


def _evdev_util() -> _Util:
    return cast(_Util, import_module("evdev.util"))


def _skip_unless_transport_ready() -> tuple[Any, str]:
    connections = discover_naga_connections()
    if len(connections) != 1:
        pytest.skip("exactly one supported Naga transport must be attached")
    connection = connections[0]
    node = next((n for n in connection.nodes if n.interface_number == "01"), None)
    if node is None:
        pytest.skip("interface 01 event node is not present")
    if not os.access(node.event_path, os.R_OK | os.W_OK):
        pytest.skip("no read/write access to the interface 01 event node")
    return connection, node.event_path


def _read_active_dpi_stage(openrazer: Any) -> tuple[int, int]:
    manager = openrazer.DeviceManager()
    for device in manager.devices:
        if "Naga V3 Pro" in device.name:
            active, stages = device.dpi_stages
            return int(active), len(stages)
    raise AssertionError("OpenRazer does not expose the Naga V3 Pro")


def _ensure_driver_mode(openrazer: Any) -> None:
    """Driver mode makes the firmware forward F13/F14/F17 reports."""
    manager = openrazer.DeviceManager()
    for device in manager.devices:
        if "Naga V3 Pro" in device.name:
            get_mode = device._dbus.get_dbus_method("getDeviceMode", "razer.device.misc")
            set_mode = device._dbus.get_dbus_method("setDeviceMode", "razer.device.misc")
            if get_mode() != "3:0":
                set_mode(0x03, 0x00)
            if get_mode() != "3:0":
                raise AssertionError("could not enable OpenRazer driver mode")
            return
    raise AssertionError("OpenRazer does not expose the Naga V3 Pro")


async def _wait_for_dpi_stage(
    openrazer: Any, expected: int, window: float, samples: list[tuple[float, int]]
) -> None:
    deadline = monotonic() + window
    next_mode_check = 0.0
    while monotonic() < deadline:
        active, _count = await asyncio.to_thread(_read_active_dpi_stage, openrazer)
        samples.append((round(monotonic(), 3), active))
        if active == expected:
            return
        if monotonic() >= next_mode_check:
            await asyncio.to_thread(_ensure_driver_mode, openrazer)
            next_mode_check = monotonic() + 2.0
        await asyncio.sleep(0.25)
    raise AssertionError(f"DPI stage {expected} was not reached within {window:g}s")


def _find_node_path(name: str) -> str | None:
    factory = _input_device_factory()
    for path in _evdev_util().list_devices():
        try:
            device = factory(path, readonly=True)
        except OSError:
            continue
        try:
            if device.name == name:
                return path
        finally:
            device.close()
    return None


async def _watch_virtual_keyboard(events: list[tuple[int, int, int]]) -> str | None:
    deadline = monotonic() + 10.0
    path = None
    while monotonic() < deadline:
        path = _find_node_path(VIRTUAL_KEYBOARD_NAME)
        if path is not None:
            break
        await asyncio.sleep(0.1)
    if path is None:
        return None
    device = _input_device_factory()(path, readonly=True)
    try:
        async for event in device.async_read_loop():
            events.append((event.type, event.code, event.value))
    finally:
        device.close()


async def _wait_for_alt_transitions(
    events: list[tuple[int, int, int]], window: float, sessions: list[Any], proxy_name: str
) -> None:
    deadline = monotonic() + window
    next_probe = 0.0
    while monotonic() < deadline:
        presses = [value for kind, code, value in events if kind == EV_KEY and code == KEY_LEFTALT]
        if (
            1 in presses
            and 0 in presses
            and presses.index(1) < len(presses) - presses[::-1].index(0)
        ):
            return
        if monotonic() >= next_probe:
            keyboard_present = _find_node_path(VIRTUAL_KEYBOARD_NAME) is not None
            proxy_present = _find_node_path(proxy_name) is not None
            session_running = all(session.running for session in sessions)
            session_errors = [repr(error) for session in sessions for error in session.errors]
            print(
                f"probe: events={len(events)} keyboard={keyboard_present} "
                f"proxy={proxy_present} readers_running={session_running} errors={session_errors}",
                flush=True,
            )
            next_probe = monotonic() + 2.0
        await asyncio.sleep(0.1)
    raise AssertionError(f"no complete LEFTALT down/up observed within {window:g}s")


async def _wait_for_node_removal(name: str, window: float = 5.0) -> None:
    deadline = monotonic() + window
    while monotonic() < deadline:
        if _find_node_path(name) is None:
            return
        await asyncio.sleep(0.2)


def _verify_grab_released(event_path: str) -> None:
    device = _input_device_factory()(event_path)
    try:
        device.grab()
        device.ungrab()
    finally:
        device.close()


async def test_first_slice_dpi_stages_and_held_alt() -> None:
    logging.basicConfig(level=logging.DEBUG, format="%(name)s %(message)s")
    connection, event_path = _skip_unless_transport_ready()
    proxy_name = f"Naga Control Forwarding Proxy 1532:{connection.product_id}/interface-01"
    openrazer = import_module("openrazer.client")
    _ensure_driver_mode(openrazer)
    dpi_samples: list[tuple[float, int]] = []

    worker = HardwareWorker(OpenRazerBackend())
    real_session_factory = create_session_factory(worker)
    sessions: list[Any] = []

    def recording_session_factory(connection: Any, configuration: Any) -> Any:
        session = real_session_factory(connection, configuration)
        sessions.append(session)
        return session

    service = NagaService(
        discover_naga_connections,
        lambda: default_configuration(),
        worker,
        recording_session_factory,
    )
    alt_events: list[tuple[int, int, int]] = []
    watcher: asyncio.Task[str | None] | None = None
    result: dict[str, Any] = {
        "date": datetime.now(UTC).isoformat(),
        "kernel": platform.release(),
        "python_evdev": version("evdev"),
        "transport": connection.transport,
        "plate": 12,
        "desktop": "wayland" if os.environ.get("WAYLAND_DISPLAY") else "xorg",
    }
    try:
        state = await service.start()
        assert state.status == "available", f"OpenRazer backend is not available: {state.error}"
        # Profile-settings application wrote the desired stages; re-read the baseline.
        initial_stage, stage_count = await asyncio.to_thread(_read_active_dpi_stage, openrazer)
        expected_up = min(initial_stage + 1, stage_count)
        expected_back = expected_up - 1 if expected_up > initial_stage else initial_stage
        dpi_samples.append((round(monotonic(), 3), initial_stage))
        deadline = monotonic() + 15.0
        while monotonic() < deadline and _find_node_path(proxy_name) is None:
            await asyncio.sleep(0.1)
        assert _find_node_path(proxy_name) is not None, "forwarding proxy did not become visible"
        watcher = asyncio.create_task(_watch_virtual_keyboard(alt_events))

        print(
            f"STEP 1: press F13 (DPI up). Expect stage {initial_stage} -> {expected_up}",
            flush=True,
        )
        await _wait_for_dpi_stage(openrazer, expected_up, PRESS_WINDOW_SECONDS, dpi_samples)

        print(
            f"STEP 2: press F14 (DPI down). Expect stage {expected_up} -> {expected_back}",
            flush=True,
        )
        await _wait_for_dpi_stage(openrazer, expected_back, PRESS_WINDOW_SECONDS, dpi_samples)

        print("STEP 3: hold F17 for about one second, then release.", flush=True)
        await _wait_for_alt_transitions(alt_events, PRESS_WINDOW_SECONDS, sessions, proxy_name)

        key_sequence = [(kind, code, value) for kind, code, value in alt_events if kind != EV_SYN]
        leftalt_sequence = [event for event in key_sequence if event[1] == KEY_LEFTALT]
        assert leftalt_sequence == [(EV_KEY, KEY_LEFTALT, 1), (EV_KEY, KEY_LEFTALT, 0)], (
            f"unexpected LEFTALT output: {alt_events}"
        )
        assert all(value in {0, 1} for _kind, _code, value in key_sequence), (
            f"unexpected repeat output: {key_sequence}"
        )
        syn_count = sum(1 for kind, _code, _value in alt_events if kind == EV_SYN)
        assert syn_count == len(key_sequence)
        result["outcome"] = "pass"
    finally:
        if watcher is not None:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        await service.stop()
        session_errors = [repr(error) for session in sessions for error in session.errors]
        await _wait_for_node_removal(VIRTUAL_KEYBOARD_NAME)
        for interface in ("00", "01", "02"):
            await _wait_for_node_removal(
                f"Naga Control Forwarding Proxy 1532:{connection.product_id}/interface-{interface}"
            )
        _verify_grab_released(event_path)
        for node in connection.nodes:
            _verify_grab_released(node.event_path)
        result.setdefault("outcome", "fail")
        result["dpi_samples"] = dpi_samples
        result["alt_events"] = alt_events
        result["session_errors"] = session_errors
        report_path = REPORT_PATH.with_name(f"{connection.transport}-first-slice-validation.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"session errors: {session_errors}", flush=True)
        print(f"report: {report_path} outcome={result['outcome']}", flush=True)
