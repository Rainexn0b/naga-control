"""Human-operated UI-06 checks. Never run as part of the default test suite.

Stop the installed user service and quit the GUI; stop other remappers. Attach
only one supported transport and keep a second keyboard available. Run as the
logged-in user, with live TTY input and visible prompts (not via an API runner):

    NAGA_UI06_HARDWARE=1 .venv/bin/pytest -m hardware -s tests/hardware/test_ui06_guided.py

The optional natural sleep check is in test_ui06_sleep.py.
No test configuration is saved. The held-key test applies the saved active
profile's hardware settings on startup; review those settings before running.
On any timeout, release all mouse buttons; the TTY reader is detached.
"""

import asyncio
import logging
import os
import subprocess
import sys
from dataclasses import replace
from importlib import import_module
from pathlib import Path
from time import monotonic
from typing import Protocol, cast

import pytest

from naga_control.adapters.config.storage import TomlConfigStore, default_config_path
from naga_control.adapters.evdev.discovery import NagaConnection, discover_naga_connections
from naga_control.adapters.evdev.source import open_evdev_source
from naga_control.adapters.openrazer.backend import OpenRazerBackend
from naga_control.adapters.openrazer.lifecycle_monitor import OpenRazerLifecycleMonitor
from naga_control.adapters.uinput.keyboard import VirtualKeyboard, create_virtual_keyboard
from naga_control.adapters.uinput.mouse import create_virtual_mouse
from naga_control.adapters.uinput.proxy import UInputForwardingProxyFactory
from naga_control.adapters.uinput.readiness import create_proxy_readiness_waiter
from naga_control.application.remapping import FirstSliceSession
from naga_control.application.service_factory import create_service
from naga_control.config import dump_toml
from naga_control.domain.actions import KeyAction
from naga_control.domain.hardware import DeviceMode
from naga_control.domain.intents import KeyOutputIntent
from naga_control.domain.profiles import Binding, Configuration
from naga_control.service.device_action_executor import DeviceActionExecutor
from naga_control.service.hardware_worker import HardwareWorker
from naga_control.service.runtime import NagaService

pytestmark = pytest.mark.hardware


class _InputDevice(Protocol):
    def active_keys(self) -> list[int]: ...

    def grab(self) -> None: ...

    def ungrab(self) -> None: ...

    def close(self) -> None: ...


class _InputDeviceFactory(Protocol):
    def __call__(self, path: str) -> _InputDevice: ...


class PhysicalTopology:
    def get_topology(self) -> tuple[NagaConnection, ...]:
        return discover_naga_connections()


def preflight() -> tuple[NagaConnection, tuple[str, ...]]:
    if os.environ.get("NAGA_UI06_HARDWARE") != "1":
        pytest.skip("set NAGA_UI06_HARDWARE=1 to opt in")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        pytest.skip("an interactive TTY is required; do not run through an API runner")
    if os.geteuid() == 0:
        pytest.skip("run as the logged-in user, never root")
    try:
        status = subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", "naga-control.service"],
            check=False,
            capture_output=True,
            timeout=5,
        ).returncode
    except (OSError, subprocess.TimeoutExpired):
        pytest.skip("cannot confirm installed user service is inactive")
    if status != 3:
        pytest.skip("installed user service must be present and inactive")
    try:
        connections = discover_naga_connections()
    except Exception:
        pytest.fail("physical USB discovery failed", pytrace=False)
    if len(connections) != 1 or not connections[0].nodes:
        pytest.skip("attach exactly one supported physical Naga transport")
    connection = connections[0]
    paths = tuple(node.event_path for node in connection.nodes)
    if not all(os.access(path, os.R_OK | os.W_OK) for path in paths):
        pytest.skip("physical Naga input nodes must be readable and writable")
    return connection, paths


async def prompt(message: str, seconds: float = 60) -> str:
    print(f"{message} [Enter/skip/cancel; {seconds:g}s limit]", flush=True)
    print("> ", end="", flush=True)
    loop = asyncio.get_running_loop()
    response: asyncio.Future[str] = loop.create_future()
    descriptor = sys.stdin.fileno()

    def receive() -> None:
        loop.remove_reader(descriptor)
        try:
            response.set_result(sys.stdin.readline())
        except Exception as exc:
            response.set_exception(exc)

    loop.add_reader(descriptor, receive)
    try:
        answer = await asyncio.wait_for(response, seconds)
    except (TimeoutError, OSError) as exc:
        raise RuntimeError("prompt timed out or stdin failed; release every mouse button") from exc
    finally:
        loop.remove_reader(descriptor)
    if not answer:
        raise RuntimeError("stdin closed; release every mouse button")
    answer = answer.strip().lower()
    if answer in {"skip", "cancel"}:
        pytest.skip("operator skipped or cancelled this guided check")
    if answer:
        raise RuntimeError("enter only Enter, skip, or cancel")
    return answer


def _input_devices(paths: tuple[str, ...]) -> list[_InputDevice]:
    factory = cast(_InputDeviceFactory, import_module("evdev").InputDevice)
    return [factory(path) for path in paths]


def no_grabs(paths: tuple[str, ...]) -> None:
    for path in paths:
        device = _input_devices((path,))[0]
        try:
            device.grab()
            device.ungrab()
        finally:
            device.close()


async def all_released(paths: tuple[str, ...], seconds: float = 5) -> None:
    deadline = monotonic() + seconds
    while monotonic() < deadline:
        for path in paths:
            device = _input_devices((path,))[0]
            try:
                if device.active_keys():
                    break
            finally:
                device.close()
        else:
            return
        await asyncio.sleep(0.1)
    raise RuntimeError("physical buttons still held; tap and release each button")


def mode(connections: tuple[NagaConnection, ...]) -> DeviceMode:
    backend = OpenRazerBackend()
    try:
        if backend.rescan(connections).status != "available":
            raise RuntimeError("OpenRazer device unavailable")
        return backend.read_device_mode()
    finally:
        backend.close()


async def cleanup(
    service: NagaService | None,
    original: DeviceMode,
    transport: str,
    paths: tuple[str, ...],
    monitor: OpenRazerLifecycleMonitor | None = None,
    sessions: list[FirstSliceSession] | None = None,
) -> None:
    problems: list[str] = []
    if monitor is not None:
        try:
            await monitor.stop()
        except Exception:
            problems.append("lifecycle monitor stop failed")
    if service is not None:
        try:
            await service.stop()
        except Exception:
            problems.append("service stop failed")
    for session in sessions or []:
        try:
            await session.stop()
        except Exception:
            problems.append("session stop failed")
    try:
        no_grabs(paths)
    except Exception:
        problems.append("a physical grab was not released")
    backend = OpenRazerBackend()
    try:
        current = discover_naga_connections()
        if len(current) != 1 or current[0].transport != transport or not current[0].nodes:
            problems.append("original transport unavailable: restore mode manually")
        elif backend.rescan(current).status != "available":
            problems.append("OpenRazer unavailable: restore mode manually")
        else:
            await asyncio.to_thread(backend.set_device_mode, original)
            if await asyncio.to_thread(backend.read_device_mode) != original:
                problems.append("original mode not verified: restore manually")
    except Exception:
        problems.append("original mode restore failed: restore manually")
    finally:
        backend.close()
    try:
        no_grabs(paths)
    except Exception:
        problems.append("a physical grab remains after cleanup")
    if problems:
        pytest.fail("cleanup: " + "; ".join(problems), pytrace=False)


class _RecordingKeyboard:
    def __init__(self, real: VirtualKeyboard, events: list[str]) -> None:
        self._real = real
        self._events = events
        self.held = False

    def emit(self, intent: KeyOutputIntent) -> None:
        self._real.emit(intent)
        if intent.key == "left_alt" and intent.value in {0, 1}:
            self.held = intent.value == 1
            self._events.append("alt_down" if self.held else "alt_up")

    def release_all(self) -> None:
        self._real.release_all()
        if self.held:
            self._events.append("alt_up")
        self.held = False

    def close(self) -> None:
        self._real.close()
        if self.held:
            self._events.append("alt_up")
        self.held = False


class _RecordingBackend(OpenRazerBackend):
    def __init__(self, events: list[str], paths: tuple[str, ...]) -> None:
        super().__init__()
        self._events = events
        self._paths = paths

    def set_device_mode(self, mode: DeviceMode) -> DeviceMode:
        if mode == "firmware":
            no_grabs(self._paths)
            self._events.append("no_grabs_before_write")
            self._events.append("firmware_write_begin")
        return super().set_device_mode(mode)


async def _wait_event(events: list[str], value: str, seconds: float = 30) -> None:
    deadline = monotonic() + seconds
    while monotonic() < deadline:
        if value in events:
            return
        await asyncio.sleep(0.05)
    raise RuntimeError(f"did not observe {value} within {seconds:g}s")


def _held_configuration() -> Configuration:
    saved = TomlConfigStore(default_config_path(os.environ, Path.home())).load()
    if saved is None:
        pytest.skip("save an active profile first; no default hardware settings will be invented")
    active = saved.profile(saved.active_profile)
    common = tuple(
        binding for binding in active.bindings.common if binding.control_id != "ring_finger"
    )
    bindings = replace(
        active.bindings, common=(*common, Binding("ring_finger", KeyAction("left_alt")))
    )
    profile = replace(active, bindings=bindings)
    profiles = tuple(
        (name, profile if name == saved.active_profile else other) for name, other in saved.profiles
    )
    return replace(saved, profiles=profiles, mode="software")


@pytest.mark.asyncio
async def test_held_f17_release_precedes_firmware_write() -> None:
    connection, paths = preflight()
    try:
        configuration = _held_configuration()
    except Exception:
        pytest.fail("saved active profile could not be loaded", pytrace=False)
    await prompt(
        "START confirmation: with ALL mouse buttons released, press Enter on the "
        "backup keyboard now. Do NOT hold F17 yet. GUI and remappers must be "
        "closed; only one transport attached. Saved settings are used in memory.",
        120,
    )
    await all_released(paths)
    try:
        original = await asyncio.to_thread(mode, (connection,))
    except Exception:
        pytest.fail("could not read original hardware mode", pytrace=False)
    events: list[str] = []
    keyboards: list[_RecordingKeyboard] = []
    sessions: list[FirstSliceSession] = []
    worker = HardwareWorker(_RecordingBackend(events, paths))

    def session_factory(found: NagaConnection, config: Configuration) -> FirstSliceSession:
        keyboard = _RecordingKeyboard(create_virtual_keyboard(), events)
        keyboards.append(keyboard)
        session = FirstSliceSession(
            found,
            config.profile(config.active_profile),
            keyboard,
            create_virtual_mouse(),
            DeviceActionExecutor(worker),
            open_evdev_source,
            UInputForwardingProxyFactory(),
            create_proxy_readiness_waiter(),
        )
        sessions.append(session)
        return session

    service = create_service(
        discover=discover_naga_connections,
        load_configuration=lambda: configuration,
        worker=worker,
        session_factory=session_factory,
    )
    previous_logging_level = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        print("Preparing forwarding: keep ALL mouse buttons released until HOLD F17.", flush=True)
        await service.start()
        if service.snapshot()["mode_ready"] is not True:
            raise RuntimeError("software mode and forwarding were not ready")
        print(
            "Press and HOLD the ring-finger button (F17) now. The test will advance "
            "automatically when LEFTALT goes down; KEEP HOLDING until the RELEASE prompt.",
            flush=True,
        )
        await _wait_event(events, "alt_down", seconds=90)
        if not any(keyboard.held for keyboard in keyboards):
            raise RuntimeError("generated LEFTALT did not stay held")
        node = next((n for n in connection.nodes if n.interface_number == "01"), None)
        if node is None:
            raise RuntimeError("F17 physical interface is missing")
        device = _input_devices((node.event_path,))[0]
        try:
            if 187 not in device.active_keys():
                raise RuntimeError("physical F17 is not held; do not request the handoff")
        finally:
            device.close()
        if await asyncio.to_thread(mode, (connection,)) != "software":
            raise RuntimeError("driver mode changed while F17 was held")
        firmware = replace(configuration, mode="firmware", revision=configuration.revision + 1)
        await service.apply_configuration(configuration.revision, dump_toml(firmware))
        if events[:4] != ["alt_down", "alt_up", "no_grabs_before_write", "firmware_write_begin"]:
            print("Observed handoff events:", ", ".join(events[:8]), flush=True)
            raise RuntimeError("LEFTALT and grabs were not released before firmware write")
        if (
            service.snapshot()["mode_ready"] is not True
            or service.snapshot()["observed_mode"] != "firmware"
        ):
            raise RuntimeError("firmware handoff did not verify")
        if await asyncio.to_thread(mode, (connection,)) != "firmware":
            raise RuntimeError("firmware hardware readback failed")
        no_grabs(paths)
        print("Verified LEFTALT up before mode write, firmware readback, and no grabs.", flush=True)
        await prompt("Now RELEASE F17 and all mouse buttons; press Enter on backup keyboard")
        await all_released(paths)
        software = replace(firmware, mode="software", revision=firmware.revision + 1)
        await service.apply_configuration(firmware.revision, dump_toml(software))
        if (
            service.snapshot()["mode_ready"] is not True
            or service.snapshot()["observed_mode"] != "software"
        ):
            raise RuntimeError("safe software return did not verify")
        if await asyncio.to_thread(mode, (connection,)) != "software":
            raise RuntimeError("software hardware readback failed")
        print("PASS: held-key handoff and safe return verified.", flush=True)
    except pytest.skip.Exception:
        raise
    except Exception as exc:
        pytest.fail(
            f"held-key check failed ({type(exc).__name__}); release all buttons", pytrace=False
        )
    finally:
        try:
            await cleanup(service, original, connection.transport, paths, sessions=sessions)
        finally:
            logging.disable(previous_logging_level)
