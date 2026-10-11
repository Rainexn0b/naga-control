"""Payload staging tests for the native builder (fakes only)."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from buildpython.openrazer_native import payload
from tests.openrazer_native_fakes import COMMIT, GPL_TEXT, completed_stdout

MINOR = "3.10"
PKGVER = "3.12.1.pr2904.fix2"


def _ok_runner(cmd: Sequence[str], cwd: Path | None) -> subprocess.CompletedProcess[str]:
    return completed_stdout("")


def test_install_lib_paths() -> None:
    assert payload.python_install_lib("debian", MINOR) == "/usr/lib/python3/dist-packages"
    assert payload.python_install_lib("fedora", MINOR) == f"/usr/lib/python{MINOR}/site-packages"
    with pytest.raises(ValueError, match="Unsupported family"):
        payload.python_install_lib("arch", MINOR)


def test_copy_excludes_git_and_group_transform_utf8(tmp_path: Path) -> None:
    source = tmp_path / "src"
    (source / ".git").mkdir(parents=True)
    (source / ".git" / "HEAD").write_text("ref\n", encoding="ascii")
    for relative in payload.GROUP_FILES:
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("group plugdev caf\u00e9\n", encoding="utf-8")
    dest = tmp_path / "copy"
    payload.copy_source_tree(source, dest)
    assert not (dest / ".git").exists()
    payload.apply_group_transform(dest)
    for relative in payload.GROUP_FILES:
        text = (dest / relative).read_text(encoding="utf-8")
        assert "openrazer" in text and "plugdev" not in text and "caf\u00e9" in text


def test_copy_rejects_symlink_tree(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "evil").symlink_to("/etc/passwd")
    with pytest.raises(ValueError, match="symlink"):
        payload.copy_source_tree(source, tmp_path / "copy")


def test_make_refuses_forbidden_targets(tmp_path: Path) -> None:
    for forbidden in ("driver_install", "depmod", "xdg_autostart", "install"):
        with pytest.raises(ValueError, match="allowlisted"):
            payload.run_make(tmp_path, None, tmp_path, [], [forbidden], _ok_runner)


def test_stage_driver_patches_version_and_wrapper(tmp_path: Path) -> None:
    copy_root = tmp_path / "src"
    copy_root.mkdir()
    stage = tmp_path / "stage-driver"
    wrapper_src = tmp_path / "dkms-make"
    wrapper_src.write_text("#!/bin/sh\nset -eu\n", encoding="utf-8")

    def _make(cmd: Sequence[str], cwd: Path | None) -> subprocess.CompletedProcess[str]:
        items = list(cmd)
        dest = Path(next(a for a in items if a.startswith("DESTDIR=")).split("=", 1)[1])
        dkms_dir = dest / f"usr/src/openrazer-driver-{PKGVER}"
        dkms_dir.mkdir(parents=True, exist_ok=True)
        (dkms_dir / "dkms.conf").write_text(
            'PACKAGE_NAME="openrazer-driver"\nPACKAGE_VERSION="3.12.1"\nMAKE="make"\n',
            encoding="utf-8",
        )
        return completed_stdout("")

    payload.stage_driver(copy_root, stage, PKGVER, wrapper_src, _make)
    conf = (stage / f"usr/src/openrazer-driver-{PKGVER}/dkms.conf").read_text(encoding="utf-8")
    assert f'PACKAGE_VERSION="{PKGVER}"' in conf
    assert 'MAKE="./dkms-make ${kernelver}"' in conf


def test_stage_python_uses_isolated_flags(tmp_path: Path) -> None:
    module_dir = tmp_path / "daemon"
    module_dir.mkdir()
    stage = tmp_path / "stage"
    record = tmp_path / "record.txt"
    seen: list[list[str]] = []

    def _python(cmd: Sequence[str], cwd: Path | None) -> subprocess.CompletedProcess[str]:
        seen.append(list(cmd))
        assert cwd == module_dir
        assert "-I" in cmd and "-B" in cmd
        assert "--single-version-externally-managed" in list(cmd)
        assert not any(a.startswith("--install-layout") for a in cmd)
        return completed_stdout("")

    payload.stage_python_module(
        module_dir, stage, "/usr/lib/python3/dist-packages", record, _python
    )
    assert seen and "--install-lib=/usr/lib/python3/dist-packages" in seen[0]


def test_write_doc_files_and_modes_under_umask077(tmp_path: Path) -> None:
    old_umask = os.umask(0o077)
    try:
        stage = tmp_path / "stage"
        payload.write_doc_files(stage, "openrazer-driver-dkms-local", COMMIT, GPL_TEXT)
        payload.normalize_stage_modes(stage, "openrazer-driver-dkms-local", PKGVER)
    finally:
        os.umask(old_umask)
    stamp = stage / "usr/share/doc/openrazer-driver-dkms-local/source-commit"
    assert stamp.read_text(encoding="ascii") == COMMIT + "\n"
    assert oct(stamp.stat().st_mode & 0o777) == "0o644"
    copyright_text = (stage / "usr/share/doc/openrazer-driver-dkms-local/copyright").read_text(
        encoding="utf-8"
    )
    assert "GENERAL PUBLIC LICENSE" in copyright_text
