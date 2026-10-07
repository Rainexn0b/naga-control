"""Hermetic shell harness: only harmless filesystem commands leave the fake PATH."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from tests.installer_command_fakes import FAKE

ROOT = Path(__file__).resolve().parents[1]
PIN = "26b0eeb5ed70d638fa3528851adcd5e58369a7f5"
VERSION = "3.12.1.pr2904.fix2-1"
TAG = "v0.4.0"
ROLES = ("openrazer-driver-dkms-local", "openrazer-daemon-local", "python-openrazer-local")
NAMES = tuple(f"{role}-{VERSION}-any.pkg.tar.zst" for role in ROLES)


def operation_name(command: list[str]) -> str:
    """Classify only the exact read-only manager preflight, preserving raw logs."""
    if command == ["systemctl", "--user", "show", "--property=Version", "--value"]:
        return "systemctl-status"
    return command[0]


class PackageMetadata(TypedDict):
    role: str
    pkginfo: str
    stamp: str
    members: list[str]


@dataclass
class InstallerHarness:
    root: Path
    environment: dict[str, str]

    @property
    def remote(self) -> Path:
        return self.root / "remote"

    def configure(self, **changes: object) -> None:
        path = self.root / "state.json"
        state = json.loads(path.read_text())
        state.update(changes)
        path.write_text(json.dumps(state))

    def metadata(self) -> dict[str, PackageMetadata]:
        return json.loads((self.root / "state.json").read_text())["metadata"]

    @property
    def system_python(self) -> Path:
        return self.root / "bin/system-python3"

    def stage_openrazer(self, target: Path | None = None) -> Path:
        # Test-only source substitution, never a production interpreter override.
        target = target or self.root / "install_openrazer.sh"
        source = (ROOT / "scripts/install_openrazer.sh").read_text()
        assert "/usr/bin/python3" in source
        target.write_text(
            source.replace("/usr/bin/python3", str(self.system_python)).replace(
                "/usr/lib/modules/", str(self.root / "modules") + "/"
            )
        )
        return target

    def run(
        self, *arguments: str, script: Path | None = None, input_fd: int | None = None
    ) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
        result = subprocess.run(
            ["/bin/bash", str(script or self.root / "install_openrazer.sh"), *arguments],
            env=self.environment,
            stdin=input_fd,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        log = self.root / "commands.jsonl"
        commands = (
            [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        )
        return result, commands


def harness(tmp_path: Path) -> InstallerHarness:
    root = tmp_path / "fakes"
    remote = root / "remote"
    remote.mkdir(parents=True)
    metadata: dict[str, PackageMetadata] = {}
    rows: list[str] = []
    for index, (role, name) in enumerate(zip(ROLES, NAMES, strict=True)):
        payload = (name + " fake package bytes\n").encode()
        (remote / name).write_bytes(payload)
        rows.append(f"{hashlib.sha256(payload).hexdigest()}  {name}\n")
        dependencies = ""
        if index:
            dependencies = (
                f"depend = {ROLES[index - 1]}={VERSION}\n"
                "depend = python>=3.14\ndepend = python<3.15\n"
            )
        metadata[name] = {
            "role": role,
            "pkginfo": f"pkgname = {role}\npkgver = {VERSION}\narch = any\n{dependencies}",
            "stamp": PIN + "\n",
            "members": [".PKGINFO", ".BUILDINFO", f"usr/share/doc/{role}/source-commit"],
        }
        if index:
            package = "openrazer_daemon" if index == 1 else "openrazer"
            metadata[name]["members"].append(
                f"usr/lib/python3.14/site-packages/{package}/__init__.py"
            )
    (remote / "openrazer-arch-packages.sha256").write_text("".join(rows))
    (remote / "pin.conf").write_text(
        f'OPENRAZER_FORK_REPO="Rainexn0b/openrazer"\nOPENRAZER_COMMIT="{PIN}"\n'
        'OPENRAZER_BRANCH="test-pr-2904-edualb"\n'
        'OPENRAZER_PKGVER="3.12.1.pr2904.fix2"\nOPENRAZER_PKGREL="1"\n'
    )
    state: dict[str, object] = {
        "installed": {},
        "stamps": {},
        "groups": "users openrazer",
        "download_fail": [],
        "pacman_failure": 0,
        "unit_failure": "",
        "host_python": "3.14",
        "venv_python": "3.12",
        "metadata": metadata,
    }
    (root / "state.json").write_text(json.dumps(state))
    bin_dir = root / "bin"
    bin_dir.mkdir()
    for command in (
        "id",
        "installer-helper",
        "curl",
        "pacman",
        "sudo",
        "systemctl",
        "system-python3",
        "python",
        "python3",
        "bsdtar",
        "cat",
        "busctl",
        "uname",
        "ldconfig",
        "stat",
        "install",
        "udevadm",
        "cc",
        "make",
        "dkms",
        "clang",
        "ld.lld",
        "llvm-ar",
        "llvm-nm",
        "llvm-objcopy",
        "llvm-objdump",
        "llvm-readelf",
        "llvm-strip",
    ):
        path = bin_dir / command
        path.write_text(f"#!{sys.executable}\n{FAKE}")
        path.chmod(0o755)
    safe_tools = "bash mkdir mv chmod mktemp rm rmdir dirname grep sha256sum cp cmp wc flock"
    for command in safe_tools.split():
        executable = shutil.which(command)
        assert executable is not None
        (bin_dir / command).symlink_to(executable)
    temporary = root / "temporary"
    temporary.mkdir()
    (root / "home").mkdir()
    (root / "libfuse.so.2").touch()
    (root / "fuse-device").touch()
    (root / "filesystems").write_text("nodev\tfuse\n")
    build = root / "modules/fake-kernel/build"
    build.mkdir(parents=True)
    (build / "Makefile").touch()
    (build / ".config").write_text("CONFIG_CC_IS_CLANG=y\n")
    safe_cat = shutil.which("cat")
    assert safe_cat is not None
    environment = {
        **os.environ,
        "PATH": str(bin_dir),
        "HOME": str(root / "home"),
        "TMPDIR": str(temporary),
        "FAKE_ROOT": str(root),
        "SAFE_CAT": safe_cat,
        "SAFE_STAT": shutil.which("stat") or "missing-stat",
        "USER": "wrong-inherited-user",
    }
    for key in tuple(environment):
        if key.startswith("NAGA_CONTROL_") or key in {
            "BASH_ENV",
            "ENV",
            "APPIMAGE_EXTRACT_AND_RUN",
        }:
            environment.pop(key)
    fake = InstallerHarness(root, environment)
    fake.stage_openrazer()
    return fake


def stage_app_installer(fake: InstallerHarness, *, helper: str | None = None) -> Path:
    scripts = fake.root / "checkout/scripts"
    scripts.mkdir(parents=True)
    source = (ROOT / "scripts/install_user.sh").read_text()
    source = source.replace("/dev/fuse", str(fake.root / "fuse-device"))
    source = source.replace("/sys/module/fuse", str(fake.root / "missing-fuse-module"))
    source = source.replace("/proc/filesystems", str(fake.root / "filesystems"))
    (scripts / "install_user.sh").write_text(source)
    if helper is not None:
        (scripts / "install_openrazer.sh").write_text(helper)
    (fake.remote / "70-naga-control.rules").write_text("fake tagged rule\n")
    app = fake.remote / "Naga-Control-x86_64.AppImage"
    app.write_text(f"#!{sys.executable}\n{FAKE}")
    (fake.remote / (app.name + ".sha256")).write_text(
        f"{hashlib.sha256(app.read_bytes()).hexdigest()}  {app.name}\n"
    )
    return scripts / "install_user.sh"
