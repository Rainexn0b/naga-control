"""File-truth on failure: unlink/replace/fsync/UTF8 preserve, no clobber."""

import os
from pathlib import Path

import pytest

from tests.gui_application_fakes import make_store

VENV = ["/tmp/venv/bin/python", "-m", "naga_control.gui.app", "--start-hidden"]


def test_unlink_failure_keeps_checked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = make_store(tmp_path, VENV)
    assert store.apply(True).enabled is True

    def boom(self: Path) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "unlink", boom)
    status = store.apply(False)
    assert status.enabled is True
    assert status.error is not None and "remove" in status.error.lower()
    assert store.path.is_file()


def test_replace_failure_preserves_old_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, VENV)
    assert store.apply(True).enabled is True

    def boom(*args: object, **kwargs: object) -> str:
        raise OSError("no tmp")

    monkeypatch.setattr("tempfile.mkstemp", boom)
    status = store.apply(True)
    assert status.enabled is True
    assert status.error is not None
    assert store.path.is_file()


def test_fsync_after_replace_stays_true_with_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, VENV)
    real_fsync = os.fsync
    calls: list[str] = []

    def fake_fsync(fd: int) -> None:
        # First fsync is the temp file (succeed); second is the directory (fail).
        calls.append("fsync")
        if len(calls) >= 2:
            raise OSError("dir fsync failed")
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fake_fsync)
    status = store.apply(True)
    assert status.enabled is True
    assert status.error is not None and "durability" in status.error.lower()
    assert store.path.is_file()


def test_invalid_utf8_stable_no_clobber(tmp_path: Path) -> None:
    store = make_store(tmp_path, VENV)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_bytes(b"[Desktop Entry]\nExec=\xff\xfe\n")
    loaded = store.load()
    assert loaded.enabled is False
    assert loaded.error is not None
    before = store.path.read_bytes()
    failed = store.apply(True)
    # Unreadable existing file must not be overwritten.
    assert failed.enabled is False
    assert store.path.read_bytes() == before
    removed = store.apply(False)
    assert removed.enabled is False
    assert store.path.read_bytes() == before


def test_foreign_symlink_default_off(tmp_path: Path) -> None:
    store = make_store(tmp_path, VENV)
    assert store.load().enabled is False
    assert store.load().error is None
    store.path.parent.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "real.desktop"
    target.write_text("[Desktop Entry]\n", encoding="utf-8")
    store.path.symlink_to(target)
    assert store.apply(True).enabled is False
    assert store.path.is_symlink()
