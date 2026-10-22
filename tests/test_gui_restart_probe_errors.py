"""Probe-error regressions: authoritative open wins over 3.14 exists False."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any

import pytest

from naga_control.gui.service_restart import (  # pyright: ignore[reportPrivateUsage]
    _helper_path_for,  # pyright: ignore[reportPrivateUsage]
    _mode_path_for,  # pyright: ignore[reportPrivateUsage]
    restart_service,
)


class FakeProc:
    def __init__(self, code: int = 0) -> None:
        self.returncode: int | None = None
        self._code = code

    async def communicate(self) -> tuple[bytes, bytes]:
        self.returncode = self._code
        return b"", b""

    async def wait(self) -> int:
        if self.returncode is None:
            self.returncode = self._code
        return self.returncode

    def kill(self) -> None:
        pass


def _write_bytes(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    with contextlib.suppress(OSError):
        os.chmod(path, mode)


async def test_mode_inaccessible_is_error_not_legacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_bytes(_mode_path_for(tmp_path), b"systemd\n", 0o600)

    def fake_exists(self: Path) -> bool:
        return False

    monkeypatch.setattr(Path, "exists", fake_exists)

    def fake_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(os, "open", fake_open)
    called: list[tuple[str, ...]] = []

    async def create(*argv: str, **kwargs: Any) -> FakeProc:
        called.append(argv)
        return FakeProc(code=0)

    result = await restart_service(home=tmp_path, create_process=create)  # type: ignore[arg-type]
    assert result.ok is False and result.error is not None
    assert "unreadable" in result.error.lower() or "misconfigured" in result.error.lower()
    assert called == []


async def test_helper_inaccessible_has_no_systemd_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_bytes(_mode_path_for(tmp_path), b"session\n", 0o600)
    _write_bytes(_helper_path_for(tmp_path), b"#!/usr/bin/env bash\n", 0o755)
    real_open = os.open

    def fake_exists(self: Path) -> bool:
        return False

    monkeypatch.setattr(Path, "exists", fake_exists)

    def fake_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if str(path).endswith("session-service.sh"):
            raise PermissionError(13, "Permission denied")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", fake_open)
    called: list[tuple[str, ...]] = []

    async def create(*argv: str, **kwargs: Any) -> FakeProc:
        called.append(argv)
        return FakeProc(code=0)

    result = await restart_service(home=tmp_path, create_process=create)  # type: ignore[arg-type]
    assert result.ok is False and result.error is not None
    assert "helper" in result.error.lower()
    assert called == []
