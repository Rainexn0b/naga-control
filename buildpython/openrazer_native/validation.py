"""Pre-build verification and staged payload audits (no archives)."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from buildpython.openrazer_packages.pin import read_pin

from . import recipes

Runner = Callable[[Sequence[str], Path | None], "subprocess.CompletedProcess[str]"]
ByteRunner = Callable[[Sequence[str], Path | None], "subprocess.CompletedProcess[bytes]"]


def default_runner(cmd: Sequence[str], cwd: Path | None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(cmd), cwd=cwd, check=False, capture_output=True, text=True)


def default_byte_runner(cmd: Sequence[str], cwd: Path | None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(list(cmd), cwd=cwd, check=False, capture_output=True)


def check_family(family: str) -> str:
    if family not in recipes.SUPPORTED_FAMILIES:
        raise ValueError(f"Unsupported family: {family}")
    return family


def check_not_root(euid: int) -> None:
    if euid == 0:
        raise ValueError("Refusing to run native builder as root")


def current_python_minor() -> str:
    major, minor = sys.version_info.major, sys.version_info.minor
    if major != 3 or minor < 10:
        raise ValueError("Builder requires system Python 3.10+")
    return f"{major}.{minor}"


def read_and_check_pin(pin_path: Path) -> dict[str, str]:
    pin = read_pin(pin_path)
    if pin["OPENRAZER_FORK_REPO"] != recipes.EXPECTED_REPO:
        raise ValueError("Pin fork repository does not match cohort")
    if pin["OPENRAZER_COMMIT"] != recipes.EXPECTED_COMMIT:
        raise ValueError("Pin commit does not match cohort")
    if pin["OPENRAZER_BRANCH"] not in recipes.ALLOWED_BRANCHES:
        raise ValueError("Pin branch label is not an accepted alias")
    if pin["OPENRAZER_PKGVER"] != recipes.EXPECTED_PKGVER:
        raise ValueError("Pin package version does not match cohort")
    if pin["OPENRAZER_PKGREL"] != recipes.EXPECTED_PKGREL:
        raise ValueError("Pin package release does not match cohort")
    return pin


def check_source_tree_safe(source: Path) -> None:
    for root, dirs, files in os.walk(source, topdown=True, followlinks=False):
        if ".git" in dirs:
            dirs.remove(".git")
        for name in (*dirs, *files):
            target = Path(root) / name
            try:
                st = target.lstat()
            except OSError as error:
                raise ValueError(f"Unable to inspect source tree: {error}") from error
            if stat.S_ISLNK(st.st_mode):
                raise ValueError("Source tree must not contain symlinks")
            if stat.S_ISFIFO(st.st_mode) or stat.S_ISSOCK(st.st_mode):
                raise ValueError("Source tree must not contain special files")
            if stat.S_ISCHR(st.st_mode) or stat.S_ISBLK(st.st_mode):
                raise ValueError("Source tree must not contain device nodes")
            if stat.S_ISREG(st.st_mode) and st.st_nlink > 1:
                raise ValueError("Source tree must not contain hardlinks")
            if not stat.S_ISREG(st.st_mode) and not stat.S_ISDIR(st.st_mode):
                raise ValueError("Source tree has unsupported file type")


def verify_source(source: Path, pin: dict[str, str], runner: Runner) -> None:
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Source checkout must be a real directory")
    if any(p.is_symlink() for p in source.parents):
        raise ValueError("Source path has a symlink ancestor")
    base: list[str] = [
        "git",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-C",
        str(source),
    ]
    rev = runner([*base, "rev-parse", "HEAD"], None)
    if rev.returncode != 0 or rev.stdout.strip() != pin["OPENRAZER_COMMIT"]:
        raise ValueError("Source commit does not match pin")
    status = runner([*base, "status", "--porcelain", "--untracked-files=all", "--ignored"], None)
    if status.returncode != 0 or status.stdout.strip() != "":
        raise ValueError("Source checkout is dirty (tracked, untracked, or ignored changes)")
    check_source_tree_safe(source)


def verify_output_dir(output: Path, source: Path, euid: int) -> None:
    if output.is_symlink() or not output.is_dir():
        raise ValueError("Output must be an existing real directory")
    for parent in (output, *output.parents):
        if parent.is_symlink():
            raise ValueError("Output path has a symlink ancestor")
        try:
            st = parent.stat()
        except OSError as error:
            raise ValueError(f"Unable to inspect output ancestors: {error}") from error
        mode = stat.S_IMODE(st.st_mode)
        if parent == output:
            if st.st_uid != euid:
                raise ValueError("Output directory must be owned by the current user")
            if mode & 0o022 != 0:
                raise ValueError("Output directory must not be group/other-writable")
        elif st.st_uid == 0 and (mode & 0o1000 != 0 or mode & 0o022 == 0):
            continue
        else:
            if st.st_uid not in (euid, 0) or mode & 0o022 != 0:
                raise ValueError("Output ancestor has unsafe ownership or permissions")
        if str(parent) in ("/", "/tmp"):
            break
    try:
        out_resolved, src_resolved = output.resolve(), source.resolve()
        entries = list(output.iterdir())
    except OSError as error:
        raise ValueError(f"Unable to inspect output directory: {error}") from error
    if out_resolved == src_resolved:
        raise ValueError("Output must not be the source directory")
    if out_resolved in src_resolved.parents or src_resolved in out_resolved.parents:
        raise ValueError("Output must be outside the source tree")
    if entries:
        raise ValueError("Output directory must be empty (refusing to clobber)")


def check_safe_relpath(name: str, seen: set[str]) -> str:
    cleaned = name.removeprefix("./").removeprefix("/").removesuffix("/")
    if not cleaned or cleaned in seen or cleaned.startswith("/") or "\\" in cleaned:
        raise ValueError("Unsafe or duplicate package member")
    parts = cleaned.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise ValueError("Unsafe package member path")
    if any(ord(c) < 32 or ord(c) == 127 for c in cleaned):
        raise ValueError("Unsafe package member path")
    seen.add(cleaned)
    return cleaned


def audit_script_text(role: str, text: str, pkgver: str) -> None:
    lowered = text.lower()
    for fragment in recipes.FORBIDDEN_SCRIPT_FRAGMENTS:
        if fragment.lower() in lowered:
            raise ValueError(f"Scriptlet contains forbidden fragment: {fragment}")
    if "|| true" in text or "|| :" in text:
        raise ValueError("Scriptlet must not mask DKMS failures")
    if not text.startswith("#!/bin/sh\nset -e\n"):
        raise ValueError("Scriptlet must start with a strict shell header")
    if role == "openrazer-driver-dkms-local":
        if "dkms install" in text and (
            "getent group openrazer" not in text or "groupadd -r openrazer" not in text
        ):
            raise ValueError("Driver scriptlet must create the openrazer group")
        if pkgver not in text or "dkms" not in text or "$1" not in text:
            raise ValueError("Driver scriptlet must manage matching DKMS with $1 guards")


def _check_stage_modes(stage: Path, role: str, pkgver: str) -> None:
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
            raise ValueError(f"Staged payload must not contain symlinks: {item.name}")
        try:
            mode = stat.S_IMODE(item.stat().st_mode)
        except OSError as error:
            raise ValueError(f"Unable to inspect staged modes: {error}") from error
        if item.is_dir():
            if mode != 0o755:
                raise ValueError(f"Staged directory mode must be 0755: {item}")
        elif item.is_file():
            rel = item.relative_to(stage).as_posix()
            if rel in exec_paths:
                if mode != 0o755:
                    raise ValueError(f"Staged helper mode must be 0755: {rel}")
            elif mode != 0o644:
                raise ValueError(f"Staged file mode must be 0644: {rel}")


def audit_payload_stages(
    stages: dict[str, Path], family: str, pin: dict[str, str], minor: str
) -> None:
    commit, pkgver = pin["OPENRAZER_COMMIT"], pin["OPENRAZER_PKGVER"]
    if set(stages) != set(recipes.LOCAL_ROLES):
        raise ValueError("Payload stages must cover exactly the three roles")
    for role, root in stages.items():
        try:
            stamp = root / "usr/share/doc" / role / "source-commit"
            if stamp.is_symlink() or stamp.read_text(encoding="ascii") != commit + "\n":
                raise ValueError(f"Bad source stamp: {role}")
            copyright_path = root / "usr/share/doc" / role / "copyright"
            copyright_text = copyright_path.read_text(encoding="utf-8")
            if "GENERAL PUBLIC LICENSE" not in copyright_text or len(copyright_text) < 500:
                raise ValueError(f"Payload license must be the full GPL text: {role}")
        except (OSError, UnicodeDecodeError) as error:
            raise ValueError(f"Missing source stamp or license: {role}") from error
        if (root / "etc/xdg/autostart").exists():
            raise ValueError("XDG autostart must never be staged")
        _check_stage_modes(root, role, pkgver)
    driver = stages["openrazer-driver-dkms-local"]
    try:
        conf_text = (driver / f"usr/src/{recipes.DKMS_NAME}-{pkgver}/dkms.conf").read_text(
            encoding="utf-8"
        )
        rule_text = (driver / "usr/lib/udev/rules.d/99-razer.rules").read_text(encoding="utf-8")
        mount_text = (driver / "usr/lib/udev/razer_mount").read_text(encoding="utf-8")
        unit_text = (
            stages["openrazer-daemon-local"] / "usr/lib/systemd/user/openrazer-daemon.service"
        ).read_text(encoding="utf-8")
        dbus_text = (
            stages["openrazer-daemon-local"] / "usr/share/dbus-1/services/org.razer.service"
        ).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError(f"Missing staged payload file: {error}") from error
    if f'PACKAGE_VERSION="{pkgver}"' not in conf_text:
        raise ValueError("DKMS version patch does not match cohort")
    if 'MAKE="./dkms-make ${kernelver}"' not in conf_text:
        raise ValueError("DKMS wrapper command does not match cohort")
    wrapper = driver / f"usr/src/{recipes.DKMS_NAME}-{pkgver}/dkms-make"
    if wrapper.is_symlink() or not wrapper.is_file():
        raise ValueError("Missing DKMS wrapper")
    if "plugdev" in rule_text or "openrazer" not in rule_text or "plugdev" in mount_text:
        raise ValueError("Udev payload group does not match cohort")
    for token in (
        "Type=dbus",
        "BusName=org.razer",
        "ExecStart=/usr/bin/openrazer-daemon -F",
        "WantedBy=default.target",
    ):
        if token not in unit_text:
            raise ValueError(f"User unit lacks: {token}")
    for token in (
        "Name=org.razer",
        "Exec=/usr/bin/openrazer-daemon",
        "SystemdService=openrazer-daemon.service",
    ):
        if token not in dbus_text:
            raise ValueError(f"D-Bus service lacks: {token}")
    if family == "debian":
        daemon_mod = (
            stages["openrazer-daemon-local"]
            / "usr/lib/python3/dist-packages/openrazer_daemon/__init__.py"
        )
        client_mod = (
            stages["python-openrazer-local"] / "usr/lib/python3/dist-packages/openrazer/__init__.py"
        )
    else:
        daemon_mod = (
            stages["openrazer-daemon-local"]
            / f"usr/lib/python{minor}/site-packages/openrazer_daemon/__init__.py"
        )
        client_mod = (
            stages["python-openrazer-local"]
            / f"usr/lib/python{minor}/site-packages/openrazer/__init__.py"
        )
    for module in (daemon_mod, client_mod):
        if module.is_symlink() or not module.is_file():
            raise ValueError(f"Missing Python module at declared path: {module}")
    for root in stages.values():
        for marker in ("tests", "_fake_driver"):
            if any(marker in part for path in root.rglob("*") for part in (path.parts,)):
                raise ValueError(f"Payload must exclude: {marker}")
        if family == "debian" and any("site-packages" in p.as_posix() for p in root.rglob("*")):
            raise ValueError("Debian payload must not use site-packages layout")
        if family != "debian" and any("dist-packages" in p.as_posix() for p in root.rglob("*")):
            raise ValueError("RPM payload must not use dist-packages layout")
