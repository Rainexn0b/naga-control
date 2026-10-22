"""Restart only the Naga background service (never OpenRazer)."""

from __future__ import annotations

import asyncio
import contextlib
import errno
import os
import stat
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RESTART_ARGV: tuple[str, ...] = ("systemctl", "--user", "restart", "naga-control.service")
RESTART_TIMEOUT = 30.0
_CLEANUP_TIMEOUT = 5.0
_MAX_MODE_BYTES = 32
_MODE_SYSTEMD = b"systemd\n"
_MODE_SESSION = b"session\n"
_MODE_MISCONFIGURED = "Service restart unavailable (service manager is misconfigured)."
_MODE_UNREADABLE = "Service restart unavailable (service manager is unreadable)."
_HELPER_MISSING = "Service restart unavailable (session helper is missing)."
_HELPER_UNAVAILABLE = "Service restart unavailable (session helper is unavailable)."
_SESSION_START_MISSING = "Service restart unavailable (session helper could not start)."

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


def _mode_path_for(home: Path) -> Path:
    """Canonical private mode file; never executed, only exact bytes are trusted."""
    return home / ".local/share/naga-control/service-manager"


def _helper_path_for(home: Path) -> Path:
    """Installed session helper; only invoked as fixed bash argv, never sourced."""
    return home / ".local/share/naga-control/session-service.sh"


def _current_uid() -> int | None:
    try:
        return os.geteuid()
    except AttributeError:
        pass
    try:
        return os.getuid()
    except AttributeError:
        return None


def _probe_mode(home: Path) -> str | RestartResult:
    """Return 'systemd', 'session', or a fixed error without fallback.

    Authoritative bounded open first; only ENOENT means legacy systemd.
    ELOOP is misconfigured, EACCES/EPERM and other opens are unreadable.
    Reads are bounded to _MAX_MODE_BYTES + 1 bytes and never execute.
    """
    mode_path = _mode_path_for(home)
    try:
        fd = os.open(mode_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return "systemd"
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            return RestartResult(ok=False, error=_MODE_MISCONFIGURED)
        return RestartResult(ok=False, error=_MODE_UNREADABLE)
    try:
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                return RestartResult(ok=False, error=_MODE_MISCONFIGURED)
            if (stat.S_IMODE(st.st_mode) & 0o444) == 0:
                return RestartResult(ok=False, error=_MODE_UNREADABLE)
            uid = _current_uid()
            if uid is not None and st.st_uid != uid:
                return RestartResult(ok=False, error=_MODE_MISCONFIGURED)
            data = os.read(fd, _MAX_MODE_BYTES + 1)
        finally:
            with contextlib.suppress(OSError):
                os.close(fd)
    except OSError:
        return RestartResult(ok=False, error=_MODE_UNREADABLE)
    if data == _MODE_SYSTEMD:
        return "systemd"
    if data == _MODE_SESSION:
        return "session"
    return RestartResult(ok=False, error=_MODE_MISCONFIGURED)


def _resolve_session_argv(
    home: Path,
) -> tuple[tuple[str, ...] | None, RestartResult | None]:
    """Resolve fixed bash helper argv or a fixed error without fallback.

    Authoritative bounded open first; only ENOENT means missing.
    ELOOP, unreadable, non-regular, non-absolute, or unowned helpers
    fail without a subprocess and without falling back to systemd.
    """
    helper = _helper_path_for(home)
    if not helper.is_absolute():
        return None, RestartResult(ok=False, error=_HELPER_UNAVAILABLE)
    try:
        fd = os.open(helper, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None, RestartResult(ok=False, error=_HELPER_MISSING)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            return None, RestartResult(ok=False, error=_HELPER_UNAVAILABLE)
        return None, RestartResult(ok=False, error=_HELPER_UNAVAILABLE)
    try:
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                return None, RestartResult(ok=False, error=_HELPER_UNAVAILABLE)
            if (stat.S_IMODE(st.st_mode) & 0o444) == 0:
                return None, RestartResult(ok=False, error=_HELPER_UNAVAILABLE)
            uid = _current_uid()
            if uid is not None and st.st_uid != uid:
                return None, RestartResult(ok=False, error=_HELPER_UNAVAILABLE)
        finally:
            with contextlib.suppress(OSError):
                os.close(fd)
    except OSError:
        return None, RestartResult(ok=False, error=_HELPER_UNAVAILABLE)
    return ("bash", str(helper), "restart"), None


def _resolve_restart_argv(
    home: Path | None,
) -> tuple[tuple[str, ...] | None, RestartResult | None]:
    """Choose the single fixed restart argv for the probed mode.

    Injectable via home for tests with a private tmp home so no real
    host mode, helper, or systemctl is touched. Never executes the mode
    file and never accepts an arbitrary command or path.
    """
    try:
        base = home if home is not None else Path.home()
    except OSError:
        return None, RestartResult(ok=False, error="Service restart unavailable.")
    probed = _probe_mode(base)
    if isinstance(probed, RestartResult):
        return None, probed
    if probed == "systemd":
        return RESTART_ARGV, None
    return _resolve_session_argv(base)


async def restart_service(
    *,
    timeout: float = RESTART_TIMEOUT,
    create_process: CreateProcess = asyncio.create_subprocess_exec,
    home: Path | None = None,
) -> RestartResult:
    argv, probe_error = _resolve_restart_argv(home)
    if probe_error is not None:
        return probe_error
    assert argv is not None
    try:
        proc = await create_process(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        if argv[0] == "bash":
            return RestartResult(ok=False, error=_SESSION_START_MISSING)
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
