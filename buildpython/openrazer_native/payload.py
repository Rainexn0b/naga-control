"""Private payload staging on an owned copy (no public filesystem writes)."""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from . import recipes
from .validation import Runner, check_source_tree_safe

ALLOWED_MAKE_TARGETS: tuple[str, ...] = (
    "setup_dkms",
    "udev_install",
    "appstream_install",
    "install-resources",
    "install-systemd",
    "manpages",
)

GROUP_FILES: tuple[str, ...] = (
    "daemon/openrazer_daemon/daemon.py",
    "install_files/udev/99-razer.rules",
    "install_files/udev/razer_mount",
)


def python_install_lib(family: str, minor: str) -> str:
    """Return the explicit install-lib for a family (no --install-layout)."""
    if family == "debian":
        return "/usr/lib/python3/dist-packages"
    if family in ("fedora", "opensuse"):
        return f"/usr/lib/python{minor}/site-packages"
    raise ValueError(f"Unsupported family: {family}")


def copy_source_tree(source: Path, dest: Path) -> None:
    if dest.exists():
        raise ValueError("Staging destination must not exist")
    check_source_tree_safe(source)
    shutil.copytree(source, dest, symlinks=True, ignore=shutil.ignore_patterns(".git"))
    check_source_tree_safe(dest)


def apply_group_transform(copy_root: Path) -> None:
    """Replace the upstream group with the local cohort group on the copy."""
    for relative in GROUP_FILES:
        target = copy_root / relative
        if target.is_symlink() or not target.is_file():
            raise ValueError(f"Missing group file on copy: {relative}")
        try:
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise ValueError(f"Unable to read group file: {relative}") from error
        if "plugdev" not in text:
            raise ValueError(f"Group file lacks upstream marker: {relative}")
        target.write_text(text.replace("plugdev", "openrazer"), encoding="utf-8")


def run_make(
    copy_root: Path,
    make_dir: Path | None,
    destdir: Path,
    extra: Sequence[str],
    targets: Sequence[str],
    runner: Runner,
) -> None:
    for target in targets:
        if target not in ALLOWED_MAKE_TARGETS:
            raise ValueError(f"Refusing non-allowlisted make target: {target}")
    cmd: list[str] = ["make"]
    if make_dir is not None:
        cmd += ["-C", str(make_dir)]
    cmd += [f"DESTDIR={destdir}", "PREFIX=/usr", "UDEV_PREFIX=/usr", *extra]
    cmd += list(targets)
    result = runner(cmd, copy_root)
    if result.returncode != 0:
        raise ValueError(f"Make staging failed: {' '.join(targets)}: {result.stderr.strip()}")


def stage_driver(
    copy_root: Path, stage_dir: Path, pkgver: str, dkms_make_src: Path, runner: Runner
) -> None:
    """Stage driver DKMS source, udev rules, and appstream metadata."""
    stage_dir.mkdir(parents=True, exist_ok=False)
    run_make(
        copy_root,
        None,
        stage_dir,
        [f"DKMS_VER={pkgver}"],
        ["setup_dkms", "udev_install", "appstream_install"],
        runner,
    )
    dkms_dir = stage_dir / f"usr/src/{recipes.DKMS_NAME}-{pkgver}"
    conf = dkms_dir / "dkms.conf"
    try:
        text = conf.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError("Missing staged dkms.conf") from error
    text = text.replace('PACKAGE_VERSION="3.12.1"', f'PACKAGE_VERSION="{pkgver}"')
    if "PACKAGE_VERSION=" in text and pkgver not in text:
        raise ValueError("DKMS version patch failed")
    # Normalize MAKE to the Clang-aware wrapper (reads kernel .config).
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("MAKE="):
            lines.append('MAKE="./dkms-make ${kernelver}"')
        else:
            lines.append(line)
    if not any(line.startswith("MAKE=") for line in lines):
        raise ValueError("Staged dkms.conf lacks MAKE")
    conf.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        shutil.copy2(dkms_make_src, dkms_dir / "dkms-make")
        os.chmod(dkms_dir / "dkms-make", 0o755)
    except OSError as error:
        raise ValueError(f"Unable to install DKMS wrapper: {error}") from error


def stage_daemon_resources(copy_root: Path, stage_dir: Path, runner: Runner) -> None:
    """Stage daemon scripts, D-Bus service, user unit, and manpages."""
    stage_dir.mkdir(parents=True, exist_ok=True)
    daemon_dir = copy_root / "daemon"
    run_make(
        copy_root,
        daemon_dir,
        stage_dir,
        [],
        ["install-resources", "install-systemd", "manpages"],
        runner,
    )


def stage_python_module(
    module_dir: Path, stage_dir: Path, install_lib: str, record_path: Path, runner: Runner
) -> None:
    """Install one Python tree with explicit install-lib (no eggs/network)."""
    stage_dir.mkdir(parents=True, exist_ok=True)
    python_exe = sys.executable
    cmd = [
        python_exe,
        "-I",
        "-B",
        "setup.py",
        "install",
        f"--root={stage_dir}",
        "--prefix=/usr",
        f"--install-lib={install_lib}",
        "--single-version-externally-managed",
        "--record",
        str(record_path),
    ]
    result = runner(cmd, module_dir)
    if result.returncode != 0:
        raise ValueError(f"Python staging failed in {module_dir.name}: {result.stderr.strip()}")


def find_license_text(copy_root: Path) -> str:
    candidate = copy_root / "LICENSES" / "GPL-2.0-or-later.txt"
    try:
        text = candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError(f"Missing pinned GPL license text: {error}") from error
    if "GENERAL PUBLIC LICENSE" not in text or len(text) < 500:
        raise ValueError("Pinned license text does not look like the full GPL")
    return text


def normalize_stage_modes(stage: Path, role: str, pkgver: str) -> None:
    exec_paths: set[str] = set()
    if role == "openrazer-driver-dkms-local":
        exec_paths = {
            f"usr/src/{recipes.DKMS_NAME}-{pkgver}/dkms-make",
            "usr/lib/udev/razer_mount",
        }
    elif role == "openrazer-daemon-local":
        exec_paths = {"usr/bin/openrazer-daemon"}
    for item in stage.rglob("*"):
        if item.is_symlink():
            raise ValueError("Staged payload must not contain symlinks")
        if item.is_dir():
            os.chmod(item, 0o755)
        elif item.is_file():
            rel = item.relative_to(stage).as_posix()
            os.chmod(item, 0o755 if rel in exec_paths else 0o644)


def write_doc_files(stage_dir: Path, role: str, commit: str, license_text: str) -> None:
    doc_dir = stage_dir / "usr/share/doc" / role
    doc_dir.mkdir(parents=True, exist_ok=True)
    stamp = doc_dir / "source-commit"
    if stamp.is_symlink():
        raise ValueError(f"Refusing symlink stamp: {role}")
    stamp.write_text(commit + "\n", encoding="ascii")
    os.chmod(stamp, 0o644)
    copyright_path = doc_dir / "copyright"
    copyright_path.write_text(license_text, encoding="utf-8")
    os.chmod(copyright_path, 0o644)


def prepare_stages(
    copy_root: Path,
    workdir: Path,
    family: str,
    minor: str,
    pin: dict[str, str],
    dkms_make_src: Path,
    runner: Runner,
) -> dict[str, Path]:
    """Copy-transform-stage all three roles; return role -> DESTDIR root."""
    pkgver, commit = pin["OPENRAZER_PKGVER"], pin["OPENRAZER_COMMIT"]
    install_lib = python_install_lib(family, minor)
    stages: dict[str, Path] = {role: workdir / f"stage-{role}" for role in recipes.LOCAL_ROLES}
    for stage in stages.values():
        if stage.exists():
            raise ValueError("Staging directory already exists")
    stage_driver(copy_root, stages["openrazer-driver-dkms-local"], pkgver, dkms_make_src, runner)
    stage_daemon_resources(copy_root, stages["openrazer-daemon-local"], runner)
    stage_python_module(
        copy_root / "daemon",
        stages["openrazer-daemon-local"],
        install_lib,
        workdir / "record-daemon.txt",
        runner,
    )
    stage_python_module(
        copy_root / "pylib",
        stages["python-openrazer-local"],
        install_lib,
        workdir / "record-client.txt",
        runner,
    )
    license_text = find_license_text(copy_root)
    for role, stage in stages.items():
        write_doc_files(stage, role, commit, license_text)
        normalize_stage_modes(stage, role, pkgver)
    return stages


def find_dkms_make_src() -> Path:
    """Locate the vetted dkms-make wrapper next to the Arch recipe."""
    candidate = Path(__file__).resolve().parent.parent / "openrazer_packages" / "dkms-make"
    if not candidate.is_file() or candidate.is_symlink():
        raise ValueError("Missing vetted dkms-make wrapper")
    return candidate
