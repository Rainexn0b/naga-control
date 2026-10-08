"""Fixture-only reporter runs: absolute Bash, closed PATH, persistent tripwires."""

import os
import shlex
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

REPORTER = Path(__file__).resolve().parents[1] / "scripts/distro_report.sh"
FIXTURES = Path(__file__).parent / "fixtures/os-release"
_bash = shutil.which("bash")
assert _bash is not None, "Bash is required to test the Bash reporter"
BASH = str(Path(_bash).resolve())
TRIPWIRES = (
    "curl",
    "wget",
    "sudo",
    "apt",
    "apt-get",
    "apt-cache",
    "dpkg",
    "pacman",
    "dnf",
    "rpm",
    "zypper",
    "apk",
    "systemctl",
    "busctl",
    "dbus-send",
    "gdbus",
    "udevadm",
    "modprobe",
    "dkms",
    "ldd",
    "ldconfig",
    "python",
    "python3",
    "openrazer-daemon",
    "openrazer",
    "naga-control",
    "naga-control-service",
    "naga-control-gui",
    "Naga-Control-x86_64.AppImage",
    "naga-control.AppImage",
    "AppImage",
    "id",
    "mktemp",
    "mkdir",
    "touch",
    "rm",
    "cp",
    "mv",
    "chmod",
    "chown",
    "install",
    "flock",
    "stat",
    "cat",
    "grep",
    "sed",
    "awk",
    "head",
    "tail",
    "wc",
    "readlink",
    "realpath",
    "env",
    "tee",
    "make",
    "cc",
    "mount",
    "fusermount",
    "fusermount3",
)

_UNAME = """
printf '%s\\n' "$*" >> "$FAKE_UNAME_LOG"
case "$*" in
  -s) printf '%s\\n' "$FAKE_OS"; exit "$FAKE_OS_FAILURE" ;;
  -m) printf '%s\\n' "$FAKE_ARCH"; exit "$FAKE_ARCH_FAILURE" ;;
  *) printf '%s\\n' 'unexpected uname operation' >> "$FAKE_ATTEMPTS"; exit 97 ;;
esac
"""
_TRIPWIRE = """
printf '%s\\n' "${0##*/} $*" >> "$FAKE_ATTEMPTS"
exit 97
"""
_SEAMS = """
_dr_etc_path() { printf '%s' "$FAKE_ETC"; }
_dr_vendor_path() { printf '%s' "$FAKE_VENDOR"; }
"""
_DEVICE_GUARD = """
_fixture_device_guard() {
  case "$BASH_COMMAND" in
    *'/dev/input'*|*'/dev/uinput'*|*'/dev/hidraw'*|*'/dev/fuse'*|*'/sys/'*|*'/proc/'*|*'/run/'*)
      printf '%s\\n' 'forbidden live device/bus path attempt' >> "$FAKE_ATTEMPTS"
      exit 97 ;;
  esac
}
set -T
trap _fixture_device_guard DEBUG
"""


@dataclass
class ReportHarness:
    root: Path
    environment: dict[str, str]
    etc: Path
    vendor: Path

    def run(
        self,
        *arguments: str,
        hook: str = "",
        entry: str = '_dr_main "$@"',
        seams: bool = True,
        strict: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        code = (
            f"source {shlex.quote(str(REPORTER))}\n"
            + (_SEAMS if seams else "")
            + _DEVICE_GUARD
            + hook
            + "\n"
            + entry
        )
        result = subprocess.run(
            [
                BASH,
                "--noprofile",
                "--norc",
                *(["-eu"] if strict else []),
                "-c",
                code,
                "fixture-reporter",
                *arguments,
            ],
            env=self.environment,
            cwd=self.root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        # Never treat a swallowed fake-command error as proof of read-only work.
        assert self.attempts() == "", self.attempts()
        return result

    def attempts(self) -> str:
        return (self.root / "attempts.log").read_text()

    def uname_calls(self) -> list[str]:
        return (self.root / "uname.log").read_text().splitlines()

    def fixture(self, name: str) -> None:
        self.etc.write_bytes((FIXTURES / name).read_bytes())


def harness(tmp_path: Path, data: bytes = b'ID=ubuntu\nVERSION_ID="22.04"\n') -> ReportHarness:
    binary = tmp_path / "bin"
    binary.mkdir()
    for name, body in [("uname", _UNAME), *((name, _TRIPWIRE) for name in TRIPWIRES)]:
        command = binary / name
        command.write_text(f"#!{BASH}\n" + body)
        command.chmod(0o755)
    for log in ("attempts.log", "uname.log"):
        (tmp_path / log).write_text("")
    home = tmp_path / "home"
    home.mkdir()
    (home / "keep").write_text("unchanged configuration fixture\n")
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    etc = tmp_path / "etc-os-release"
    etc.write_bytes(data)
    vendor = tmp_path / "vendor-os-release"
    vendor.write_bytes(b"ID=ubuntu\nVERSION_ID=24.04\n")
    environment = {
        "PATH": str(binary),  # Deliberately never append the live PATH.
        "HOME": str(home),
        "TMPDIR": str(temporary),
        "LC_ALL": "C",
        "FAKE_ETC": str(etc),
        "FAKE_VENDOR": str(vendor),
        "FAKE_OS": "Linux",
        "FAKE_ARCH": "x86_64",
        "FAKE_OS_FAILURE": "0",
        "FAKE_ARCH_FAILURE": "0",
        "FAKE_UNAME_LOG": str(tmp_path / "uname.log"),
        "FAKE_ATTEMPTS": str(tmp_path / "attempts.log"),
    }
    return ReportHarness(tmp_path, environment, etc, vendor)


def fields(output: str) -> dict[str, str]:
    """Test convenience only; the human-readable report has no public schema."""
    return dict(line.split(": ", 1) for line in output.splitlines() if ": " in line)


def snapshot(root: Path) -> dict[str, tuple[int, int, int, int, bytes | str | None]]:
    result: dict[str, tuple[int, int, int, int, bytes | str | None]] = {}
    for path in [root, *root.rglob("*")]:
        if path.name in {"attempts.log", "uname.log"}:
            continue  # Only the fake/trap instrumentation may write these logs.
        metadata = path.lstat()
        content: bytes | str | None = None
        if stat.S_ISREG(metadata.st_mode):
            content = path.read_bytes()
        elif stat.S_ISLNK(metadata.st_mode):
            content = os.readlink(path)
        result[str(path.relative_to(root))] = (
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
            content,
        )
    return result
