"""Optional TTY-guided natural HyperSpeed sleep/wake in firmware mode.

Run separately after reading test_ui06_guided.py's safety instructions:
    NAGA_UI06_HARDWARE=1 .venv/bin/pytest -m hardware -s tests/hardware/test_ui06_sleep.py
"""

import asyncio
import logging
from dataclasses import replace
from time import monotonic
from typing import cast

import pytest
from test_ui06_guided import (
    PhysicalTopology,
    all_released,
    cleanup,
    mode,
    no_grabs,
    preflight,
    prompt,
)

from naga_control.adapters.evdev.discovery import discover_naga_connections
from naga_control.adapters.openrazer.backend import OpenRazerBackend
from naga_control.adapters.openrazer.lifecycle_monitor import OpenRazerLifecycleMonitor
from naga_control.application.service_factory import create_session_factory
from naga_control.domain.defaults import default_configuration
from naga_control.service.hardware_worker import HardwareWorker
from naga_control.service.runtime import NagaService

pytestmark = pytest.mark.hardware


@pytest.mark.asyncio
async def test_natural_hyperspeed_firmware_sleep_wake() -> None:
    connection, paths = preflight()
    if connection.transport != "hyperspeed":
        pytest.skip("natural sleep/wake requires HyperSpeed without a wired cable")
    await prompt(
        "Quit GUI, stop other remappers, confirm backup keyboard and inactive service. "
        "This test does NOT change the idle timeout. Allow natural sleep; do not move the mouse."
    )
    await all_released(paths)
    try:
        original = await asyncio.to_thread(mode, (connection,))
    except Exception:
        pytest.fail("could not read original hardware mode", pytrace=False)
    configuration = replace(default_configuration(), mode="firmware")
    worker = HardwareWorker(OpenRazerBackend())
    service = NagaService(
        discover_naga_connections,
        lambda: configuration,
        worker,
        create_session_factory(worker),
        state_poll_interval=2,
    )
    monitor = OpenRazerLifecycleMonitor(PhysicalTopology(), service)
    previous_logging_level = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        await service.start()
        await monitor.start()
        deadline = monotonic() + 15
        while monotonic() < deadline:
            initial = service.snapshot()
            if cast(int, initial["generation"]) >= 2 and initial["mode_ready"] is True:
                break
            await asyncio.sleep(0.25)
        else:
            raise RuntimeError("initial lifecycle rescan did not settle")
        if service.snapshot()["mode_ready"] is not True:
            raise RuntimeError("firmware mode not ready before sleep")
        if await asyncio.to_thread(mode, (connection,)) != "firmware":
            raise RuntimeError("initial firmware readback failed")
        no_grabs(paths)
        await prompt(
            "Wait for NATURAL sleep (visually confirm it), then press Enter using backup keyboard; "
            "do not touch the Naga yet",
            900,
        )
        # A visual confirmation alone does not establish that OpenRazer lost the mouse.
        deadline = monotonic() + 25
        slept = False
        baseline = cast(int, service.snapshot()["generation"])
        while monotonic() < deadline:
            snapshot = service.snapshot()
            if snapshot["mode_ready"] is False and snapshot["status"] == "unavailable":
                slept = True
                baseline = cast(int, snapshot["generation"])
                break
            await asyncio.sleep(0.25)
        no_grabs(paths)
        await prompt("Wake the Naga now; press Enter on backup keyboard once awake", 60)
        if not slept:
            pytest.skip("INCONCLUSIVE: sleep was not observed by the service")
        deadline = monotonic() + 90
        recovered = False
        while monotonic() < deadline:
            snapshot = service.snapshot()
            if (
                snapshot["mode_ready"] is True
                and snapshot["observed_mode"] == "firmware"
                and cast(int, snapshot["generation"]) > baseline
            ):
                recovered = True
                break
            await asyncio.sleep(0.25)
        no_grabs(paths)
        if not recovered:
            raise RuntimeError("confirmed wake did not produce a recovered service generation")
        if await asyncio.to_thread(mode, (connection,)) != "firmware":
            raise RuntimeError("post-wake firmware readback failed")
        no_grabs(paths)
        print(
            "PASS: natural sleep observed, wake recovered, firmware readback, no grabs.", flush=True
        )
    except pytest.skip.Exception:
        raise
    except Exception as exc:
        pytest.fail(
            f"sleep/wake check failed ({type(exc).__name__}); restore mode manually if needed",
            pytrace=False,
        )
    finally:
        try:
            await cleanup(service, original, connection.transport, paths, monitor=monitor)
        finally:
            logging.disable(previous_logging_level)
