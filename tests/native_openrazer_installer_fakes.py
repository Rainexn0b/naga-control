"""Hermetic native shell harness: only harmless filesystem commands are real."""

import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path

from tests.native_openrazer_command_fakes import FAKE

ROOT = Path(__file__).resolve().parents[1]
PIN = "26b0eeb5ed70d638fa3528851adcd5e58369a7f5"
VERSION = "3.12.1.pr2904.fix2-1"
TAG = "v0.4.0"
ROLES = ("openrazer-driver-dkms-local", "openrazer-daemon-local", "python-openrazer-local")

DEBIAN_OS = 'NAME="Ubuntu"\nVERSION_ID="24.04"\nID=ubuntu\nID_LIKE=debian\n'
FEDORA_OS = 'NAME="Fedora Linux"\nVERSION_ID="42"\nID=fedora\n'
LEAP_OS = 'NAME="openSUSE Leap"\nVERSION_ID="15.6"\nID=opensuse-leap\nID_LIKE="suse opensuse"\n'
TW_OS = 'NAME="openSUSE Tumbleweed"\nVERSION_ID="20261009"\nID=opensuse-tumbleweed\nID_LIKE="opensuse suse"\n'
DEFAULT_DEBIAN_KERNEL = "6.8.0-52-generic"


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

    @property
    def system_python(self) -> Path:
        return self.root / "bin/system-python3"

    def stage_native(self, target: Path | None = None) -> Path:
        target = target or self.root / "install_openrazer_native.sh"
        source = (ROOT / "scripts/install_openrazer_native.sh").read_text()
        assert "/usr/bin/python3" in source
        assert "/etc/os-release" in source
        assert "del sys.argv[1]" in source
        target.write_text(
            source.replace("/usr/bin/python3", str(self.system_python))
            .replace("/usr/lib/modules/", str(self.root / "modules") + "/")
            .replace("/lib/modules/", str(self.root / "modules") + "/")
            .replace("/etc/os-release", str(self.root / "os-release"))
            .replace("/usr/lib/os-release", str(self.root / "vendor-os-release"))
        )
        return target

    def run(
        self, *arguments: str, script: Path | None = None, input_fd: int | None = None
    ) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
        result = subprocess.run(
            ["/bin/bash", str(script or self.root / "install_openrazer_native.sh"), *arguments],
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


def _write_code_tar(path: Path) -> None:
    top = "naga-control-" + "a" * 40
    files = {
        "buildpython/__init__.py": b"",
        "buildpython/openrazer_native/__init__.py": b"",
        "buildpython/openrazer_native/__main__.py": b"# fake entry\n",
        "buildpython/openrazer_native/build.py": b"# fake builder\n",
        "buildpython/openrazer_packages/pin.py": b"# fake pin\n",
        "buildpython/openrazer_packages/pin.conf": (
            'OPENRAZER_FORK_REPO="Rainexn0b/openrazer"\n'
            f'OPENRAZER_COMMIT="{PIN}"\n'
            'OPENRAZER_BRANCH="naga-v3-pro-compat"\n'
            'OPENRAZER_PKGVER="3.12.1.pr2904.fix2"\nOPENRAZER_PKGREL="1"\n'
        ).encode(),
        "buildpython/openrazer_packages/dkms-make": b"# fake dkms\n",
    }
    with tarfile.open(path, "w:gz") as tar:
        for rel, data in files.items():
            arcname = f"{top}/{rel}"
            info = tarfile.TarInfo(arcname)
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))


def harness(tmp_path: Path) -> InstallerHarness:
    root = tmp_path / "fakes"
    remote = root / "remote"
    remote.mkdir(parents=True)
    _write_code_tar(remote / "naga-code.tar.gz")
    state: dict[str, object] = {
        "installed": {},
        "partial": [],
        "groups": "users",
        "download_fail": [],
        "prereq_failure": 0,
        "pkg_failure": 0,
        "builder_fail": 0,
        "builder_bad": "",
        "git_fail": 0,
        "git_dirty": 0,
        "git_dead_branch": 0,
        "git_head": PIN,
        "host_python": "3.12",
        "venv_python": "3.12",
        "python_root": False,
        "python_client": False,
        "python_daemon": False,
        "python_discover_error": 0,
        "python_malformed": "",
        "foreign_owner": 0,
        "os": "Linux",
        "arch": "x86_64",
        "kernel": DEFAULT_DEBIAN_KERNEL,
        "kernel_evr": "6.10.5-1.1",
        "whatprovides_fail": 0,
        "query_fail": 0,
        "query_malformed": "",
        "naga_sha": "a" * 40,
        "code_tar": "good",
        "systemd_failure": 0,
        "bus_failure": 0,
        "group_failure": 0,
        "unit_failure": "",
    }
    (root / "state.json").write_text(json.dumps(state))
    bin_dir = root / "bin"
    bin_dir.mkdir()
    for command in (
        "id",
        "uname",
        "curl",
        "git",
        "dpkg-query",
        "rpm",
        "apt-get",
        "dnf",
        "zypper",
        "sudo",
        "systemctl",
        "busctl",
        "system-python3",
        "python",
        "python3",
        "stat",
        "cc",
        "make",
        "dkms",
        "gcc",
        "clang",
        "ld.lld",
        "llvm-ar",
        "llvm-nm",
        "llvm-objcopy",
        "llvm-objdump",
        "llvm-readelf",
        "llvm-strip",
        "dpkg-deb",
        "rpmbuild",
        "rpm2cpio",
    ):
        path = bin_dir / command
        path.write_text(f"#!{sys.executable}\n{FAKE}")
        path.chmod(0o755)
    safe_tools = (
        "bash mkdir mv chmod mktemp rm rmdir dirname grep sha256sum cp cmp wc flock cat head ls"
    )
    for command in safe_tools.split():
        executable = shutil.which(command)
        assert executable is not None
        (bin_dir / command).symlink_to(executable)
    temporary = root / "temporary"
    temporary.mkdir()
    (root / "home").mkdir()
    (root / "os-release").write_text(DEBIAN_OS)
    (root / "vendor-os-release").write_text(DEBIAN_OS)
    build = root / f"modules/{DEFAULT_DEBIAN_KERNEL}/build"
    build.mkdir(parents=True)
    (build / "Makefile").touch()
    (build / ".config").write_text("CONFIG_CC_IS_CLANG=y\n")
    safe_stat = shutil.which("stat")
    assert safe_stat is not None
    environment = {
        **os.environ,
        "PATH": str(bin_dir),
        "HOME": str(root / "home"),
        "TMPDIR": str(temporary),
        "FAKE_ROOT": str(root),
        "SAFE_STAT": safe_stat,
        "USER": "wrong-inherited-user",
    }
    for key in tuple(environment):
        if key.startswith("NAGA_CONTROL_") or key in {
            "BASH_ENV",
            "ENV",
            "PYTHONPATH",
            "VIRTUAL_ENV",
        }:
            environment.pop(key)
    fake = InstallerHarness(root, environment)
    fake.stage_native()
    return fake


def write_os(fake: InstallerHarness, text: str | bytes) -> None:
    target = fake.root / "os-release"
    if isinstance(text, bytes):
        target.write_bytes(text)
    else:
        target.write_text(text)


def write_vendor(fake: InstallerHarness, text: str | bytes) -> None:
    target = fake.root / "vendor-os-release"
    if isinstance(text, bytes):
        target.write_bytes(text)
    else:
        target.write_text(text)


def mutations(commands: list[list[str]]) -> list[list[str]]:
    return [c for c in commands if c[0] == "sudo"]
