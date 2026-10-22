"""Session-mode restart: fixed bash helper with bounded mode probe (fake-only)."""

from __future__ import annotations

import asyncio
import contextlib
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from naga_control.gui.service_restart import (  # pyright: ignore[reportPrivateUsage]
    _helper_path_for,  # pyright: ignore[reportPrivateUsage]
    _mode_path_for,  # pyright: ignore[reportPrivateUsage]
    restart_service,
)

EXPECTED_SYSTEMD = ("systemctl", "--user", "restart", "naga-control.service")


class FakeProc:
    def __init__(self, code: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.returncode: int | None = None
        self._code = code
        self._out = stdout
        self._err = stderr
        self.killed = False
        self.waited = False

    async def communicate(self) -> tuple[bytes, bytes]:
        self.returncode = self._code
        return self._out, self._err

    async def wait(self) -> int:
        self.waited = True
        if self.returncode is None:
            self.returncode = self._code
        return self.returncode

    def kill(self) -> None:
        self.killed = True


def _write_mode(home: Path, data: bytes) -> Path:
    path = _mode_path_for(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)
    return path


def _write_helper(home: Path, data: bytes = b"#!/usr/bin/env bash\n") -> Path:
    path = _helper_path_for(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    with contextlib.suppress(OSError):
        os.chmod(path, 0o755)
    return path


async def test_missing_mode_uses_systemd(tmp_path: Path) -> None:
    seen: list[tuple[tuple[str, ...], dict[str, Any]]] = []
    proc = FakeProc(code=0)

    async def create(*argv: str, **kwargs: Any) -> FakeProc:
        seen.append((argv, kwargs))
        return proc

    result = await restart_service(home=tmp_path, create_process=create)  # type: ignore[arg-type]
    assert result.ok is True
    assert len(seen) == 1 and seen[0][0] == EXPECTED_SYSTEMD


async def test_systemd_mode_uses_systemctl(tmp_path: Path) -> None:
    _write_mode(tmp_path, b"systemd\n")
    _write_helper(tmp_path)
    seen: list[tuple[str, ...]] = []
    proc = FakeProc(code=0)

    async def create(*argv: str, **kwargs: Any) -> FakeProc:
        seen.append(argv)
        return proc

    result = await restart_service(home=tmp_path, create_process=create)  # type: ignore[arg-type]
    assert result.ok is True
    assert seen == [EXPECTED_SYSTEMD]


async def test_session_mode_uses_fixed_bash_helper(tmp_path: Path) -> None:
    _write_mode(tmp_path, b"session\n")
    helper = _write_helper(tmp_path)
    seen: list[tuple[str, ...]] = []
    proc = FakeProc(code=0)

    async def create(*argv: str, **kwargs: Any) -> FakeProc:
        seen.append(argv)
        return proc

    result = await restart_service(home=tmp_path, create_process=create)  # type: ignore[arg-type]
    assert result.ok is True and result.error is None
    assert len(seen) == 1
    assert seen[0] == ("bash", str(helper), "restart")
    assert Path(seen[0][1]).is_absolute()


async def test_session_success_redacts_helper_output(tmp_path: Path) -> None:
    _write_mode(tmp_path, b"session\n")
    _write_helper(tmp_path)
    secret = b"helper-secret-token-xyz\nsecond line"
    proc = FakeProc(code=0, stdout=secret, stderr=secret)

    async def create(*argv: str, **kwargs: Any) -> FakeProc:
        assert argv[0] == "bash" and argv[2] == "restart"
        return proc

    result = await restart_service(home=tmp_path, create_process=create)  # type: ignore[arg-type]
    assert result.ok is True and result.error is None


async def test_session_nonzero_redacts_without_secret(tmp_path: Path) -> None:
    _write_mode(tmp_path, b"session\n")
    _write_helper(tmp_path)
    proc = FakeProc(code=3, stdout=b"secret-out", stderr=b"secret-err-xyz")

    async def create(*argv: str, **kwargs: Any) -> FakeProc:
        return proc

    result = await restart_service(home=tmp_path, create_process=create)  # type: ignore[arg-type]
    assert result.ok is False
    assert result.error is not None and "exit 3" in result.error
    assert "secret-err-xyz" not in result.error and "\n" not in result.error


async def test_malformed_modes_fail_without_subprocess(tmp_path: Path) -> None:
    bad_values = [b"", b"systemd", b"session", b"SYSTEMD\n", b"foo\n", b"systemd\n\n"]
    called: list[tuple[str, ...]] = []

    async def create(*argv: str, **kwargs: Any) -> FakeProc:
        called.append(argv)
        return FakeProc(code=0)

    for bad in bad_values:
        _write_mode(tmp_path, bad)
        _write_helper(tmp_path)
        called.clear()
        result = await restart_service(home=tmp_path, create_process=create)  # type: ignore[arg-type]
        assert result.ok is False and result.error is not None
        assert called == [], f"mode {bad!r} must not start a subprocess"


async def test_oversized_mode_fails_without_subprocess(tmp_path: Path) -> None:
    _write_mode(tmp_path, b"x" * 256 + b"\n")
    called: list[tuple[str, ...]] = []

    async def create(*argv: str, **kwargs: Any) -> FakeProc:
        called.append(argv)
        return FakeProc(code=0)

    result = await restart_service(home=tmp_path, create_process=create)  # type: ignore[arg-type]
    assert result.ok is False and result.error is not None
    assert "misconfigured" in result.error.lower() or "unreadable" in result.error.lower()
    assert called == []


async def test_large_mode_is_bounded(tmp_path: Path) -> None:
    _write_mode(tmp_path, b"A" * 65536)
    called: list[tuple[str, ...]] = []

    async def create(*argv: str, **kwargs: Any) -> FakeProc:
        called.append(argv)
        return FakeProc(code=0)

    result = await restart_service(home=tmp_path, create_process=create)  # type: ignore[arg-type]
    assert result.ok is False
    assert called == []


async def test_symlink_mode_fails_without_subprocess(tmp_path: Path) -> None:
    target = tmp_path / "real-mode"
    target.write_bytes(b"systemd\n")
    link = _mode_path_for(tmp_path)
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(target)
    called: list[tuple[str, ...]] = []

    async def create(*argv: str, **kwargs: Any) -> FakeProc:
        called.append(argv)
        return FakeProc(code=0)

    result = await restart_service(home=tmp_path, create_process=create)  # type: ignore[arg-type]
    assert result.ok is False and result.error is not None
    assert called == []


async def test_directory_mode_fails_without_subprocess(tmp_path: Path) -> None:
    path = _mode_path_for(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() or path.is_symlink():
        path.unlink()
    path.mkdir(parents=True, exist_ok=True)
    called: list[tuple[str, ...]] = []

    async def create(*argv: str, **kwargs: Any) -> FakeProc:
        called.append(argv)
        return FakeProc(code=0)

    result = await restart_service(home=tmp_path, create_process=create)  # type: ignore[arg-type]
    assert result.ok is False
    assert called == []


async def test_unreadable_mode_fails_without_subprocess(tmp_path: Path) -> None:
    path = _write_mode(tmp_path, b"systemd\n")
    os.chmod(path, 0o000)
    called: list[tuple[str, ...]] = []

    async def create(*argv: str, **kwargs: Any) -> FakeProc:
        called.append(argv)
        return FakeProc(code=0)

    try:
        result = await restart_service(home=tmp_path, create_process=create)  # type: ignore[arg-type]
    finally:
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)
    assert result.ok is False and result.error is not None
    assert called == []


async def test_session_missing_helper_has_no_fallback(tmp_path: Path) -> None:
    _write_mode(tmp_path, b"session\n")
    called: list[tuple[str, ...]] = []

    async def create(*argv: str, **kwargs: Any) -> FakeProc:
        called.append(argv)
        return FakeProc(code=0)

    result = await restart_service(home=tmp_path, create_process=create)  # type: ignore[arg-type]
    assert result.ok is False
    assert result.error is not None and "helper" in result.error.lower()
    assert called == []


async def test_session_symlink_helper_fails(tmp_path: Path) -> None:
    _write_mode(tmp_path, b"session\n")
    real = tmp_path / "real-helper.sh"
    real.write_bytes(b"#!/usr/bin/env bash\n")
    link = _helper_path_for(tmp_path)
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(real)
    called: list[tuple[str, ...]] = []

    async def create(*argv: str, **kwargs: Any) -> FakeProc:
        called.append(argv)
        return FakeProc(code=0)

    result = await restart_service(home=tmp_path, create_process=create)  # type: ignore[arg-type]
    assert result.ok is False
    assert called == []


async def test_session_directory_helper_fails(tmp_path: Path) -> None:
    _write_mode(tmp_path, b"session\n")
    path = _helper_path_for(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() or path.is_symlink():
        path.unlink()
    path.mkdir(parents=True, exist_ok=True)
    called: list[tuple[str, ...]] = []

    async def create(*argv: str, **kwargs: Any) -> FakeProc:
        called.append(argv)
        return FakeProc(code=0)

    result = await restart_service(home=tmp_path, create_process=create)  # type: ignore[arg-type]
    assert result.ok is False
    assert called == []


async def test_session_unreadable_helper_fails(tmp_path: Path) -> None:
    _write_mode(tmp_path, b"session\n")
    path = _write_helper(tmp_path)
    os.chmod(path, 0o000)
    called: list[tuple[str, ...]] = []

    async def create(*argv: str, **kwargs: Any) -> FakeProc:
        called.append(argv)
        return FakeProc(code=0)

    try:
        result = await restart_service(home=tmp_path, create_process=create)  # type: ignore[arg-type]
    finally:
        with contextlib.suppress(OSError):
            os.chmod(path, 0o755)
    assert result.ok is False
    assert called == []


async def test_session_timeout_kills_and_joins(tmp_path: Path) -> None:
    _write_mode(tmp_path, b"session\n")
    _write_helper(tmp_path)

    class HangingProc(FakeProc):
        async def communicate(self) -> tuple[bytes, bytes]:
            await asyncio.sleep(60)
            return b"", b""

    proc = HangingProc()
    seen: list[tuple[str, ...]] = []

    async def create(*argv: str, **kwargs: Any) -> HangingProc:
        seen.append(argv)
        return proc

    result = await restart_service(home=tmp_path, timeout=0.02, create_process=create)  # type: ignore[arg-type]
    assert result.ok is False
    assert result.error is not None and "timed out" in result.error.lower()
    assert "uncertain" in result.error.lower()
    assert proc.killed is True and proc.waited is True
    assert seen[0][0] == "bash"


async def test_session_bash_missing_is_clear_error(tmp_path: Path) -> None:
    _write_mode(tmp_path, b"session\n")
    _write_helper(tmp_path)

    async def create(*argv: str, **kwargs: Any) -> FakeProc:
        raise FileNotFoundError("no bash")

    result = await restart_service(home=tmp_path, create_process=create)  # type: ignore[arg-type]
    assert result.ok is False
    assert result.error is not None and "could not start" in result.error.lower()


async def test_mode_file_is_never_executed(tmp_path: Path) -> None:
    _write_mode(tmp_path, b"bash evil-command\n")
    _write_helper(tmp_path)
    called: list[tuple[str, ...]] = []

    async def create(*argv: str, **kwargs: Any) -> FakeProc:
        called.append(argv)
        return FakeProc(code=0)

    result = await restart_service(home=tmp_path, create_process=create)  # type: ignore[arg-type]
    assert result.ok is False
    assert called == []


async def test_probes_use_nonblock_no_follow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_mode(tmp_path, b"session\n")
    _write_helper(tmp_path)
    real_open = os.open
    seen: list[int] = []

    def fake_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        seen.append(flags)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", fake_open)

    async def create(*argv: str, **kwargs: Any) -> FakeProc:
        return FakeProc(code=0)

    result = await restart_service(home=tmp_path, create_process=create)  # type: ignore[arg-type]
    assert result.ok is True and len(seen) == 2
    for flags in seen:
        assert flags & os.O_NONBLOCK and flags & os.O_NOFOLLOW


async def test_fifo_like_rejected_without_hang(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_mode(tmp_path, b"session\n")
    _write_helper(tmp_path)
    uid = os.geteuid()

    def fake_fstat(fd: int) -> Any:
        return type("F", (), {"st_mode": stat.S_IFIFO | 0o600, "st_uid": uid})()

    monkeypatch.setattr(os, "fstat", fake_fstat)
    called: list[tuple[str, ...]] = []

    async def create(*argv: str, **kwargs: Any) -> FakeProc:
        called.append(argv)
        return FakeProc(code=0)

    result = await restart_service(home=tmp_path, create_process=create)  # type: ignore[arg-type]
    assert result.ok is False and called == []
