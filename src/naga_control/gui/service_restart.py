"""Restart only the Naga background service (never OpenRazer)."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

RESTART_ARGV: tuple[str, ...] = ("systemctl", "--user", "restart", "naga-control.service")
RESTART_TIMEOUT = 30.0
_CLEANUP_TIMEOUT = 5.0

CreateProcess = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class RestartResult:
    ok: bool
    error: str | None = None


async def _join_verified(proc: Any) -> bool:
    try:
        if proc.returncode is None:
            with contextlib.suppress(Exception):
                proc.kill()
    except Exception:
        pass
    try:
        await asyncio.wait_for(proc.wait(), _CLEANUP_TIMEOUT)
    except TimeoutError:
        return False
    except asyncio.CancelledError:
        return False
    except Exception:
        try:
            return proc.returncode is not None
        except Exception:
            return False
    try:
        return proc.returncode is not None
    except Exception:
        return False


async def _shielded_join(proc: Any) -> bool:
    task = asyncio.create_task(_join_verified(proc))
    cancellation: asyncio.CancelledError | None = None
    while True:
        try:
            verified = await asyncio.shield(task)
            break
        except asyncio.CancelledError as exc:
            if task.cancelled():
                raise
            if cancellation is None:
                cancellation = exc
    if cancellation is not None:
        raise cancellation
    return verified


async def restart_service(
    *,
    timeout: float = RESTART_TIMEOUT,
    create_process: CreateProcess = asyncio.create_subprocess_exec,
) -> RestartResult:
    try:
        proc = await create_process(
            *RESTART_ARGV,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return RestartResult(ok=False, error="Service restart unavailable (systemctl not found).")
    except OSError:
        return RestartResult(ok=False, error="Service restart unavailable.")
    try:
        try:
            await asyncio.wait_for(proc.communicate(), timeout)
        except TimeoutError:
            verified = await _shielded_join(proc)
            if not verified:
                return RestartResult(
                    ok=False,
                    error="Service restart cleanup unverified (outcome uncertain; check status).",
                )
            return RestartResult(
                ok=False,
                error="Service restart timed out (outcome uncertain; check status).",
            )
        code = proc.returncode
        if code == 0:
            return RestartResult(ok=True, error=None)
        return RestartResult(ok=False, error=f"Service restart failed (exit {code}).")
    except asyncio.CancelledError:
        try:
            await _shielded_join(proc)
        except asyncio.CancelledError:
            raise
        raise
    except Exception:
        try:
            if proc.returncode is None:
                verified = await _shielded_join(proc)
                if not verified:
                    return RestartResult(
                        ok=False,
                        error="Service restart cleanup unverified (outcome uncertain; check status).",
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        return RestartResult(ok=False, error="Service restart failed.")
