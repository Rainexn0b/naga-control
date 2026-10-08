"""Shared closed-PATH fakes for the portable toolchain driver (no real Docker)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO / "buildpython/steps/appimage/Dockerfile.portable"
SCRIPT = REPO / "buildpython/steps/appimage/portable-build.sh"
INNER = REPO / "buildpython/steps/appimage/portable-inner.sh"
BASE_IMAGE = "ubuntu:22.04@sha256:08ea48a03a3e78ebc7cd526e6a275053223aadd88bfc09cc49b06d5281525fde"
PYTHON_URL = "https://www.python.org/ftp/python/3.12.15/Python-3.12.15.tar.xz"
PYTHON_SHA = "c2c4321961fab0fb999d66e0cecf521c2ab3994c7992873ea99e306c1094fd5a"
CONTROL_BIN = "/opt/naga-python/bin/python3.12"
CANDIDATE = (
    "portable artifact verified: static ABI gate pass + "
    "Ubuntu 22.04 baseline userspace smoke pass "
    "(desktop/hardware acceptance still required)"
)
VERIFIED = CANDIDATE
PENDING = "candidate build; finished-artifact ABI/launch acceptance pending"

ALLOWED_APT = frozenset(
    {
        "build-essential",
        "ca-certificates",
        "curl",
        "pkg-config",
        "libssl-dev",
        "libffi-dev",
        "zlib1g-dev",
        "libbz2-dev",
        "liblzma-dev",
        "libreadline-dev",
        "libsqlite3-dev",
        "libgdbm-dev",
        "libncursesw5-dev",
        "libglib2.0-0",
        "libdbus-1-dev",
        "libglib2.0-dev",
        "libudev1",
        "squashfs-tools",
        "binutils",
        "libegl1",
        "libgl1",
        "libxkbcommon0",
        "libfontconfig1",
        "libdbus-1-3",
        "libarchive-tools",
        "util-linux",
    }
)

FAKE = r"""
import json
import os
import sys
from pathlib import Path

name = Path(sys.argv[0]).name
args = sys.argv[1:]
root = Path(os.environ["FAKE_ROOT"])
state = json.loads((root / "state.json").read_text())
with (root / "commands.jsonl").open("a") as log:
    log.write(json.dumps([name, *args]) + "\n")
if name == "id":
    if args == ["-u"]:
        print(state.get("uid", "1000"))
    elif args == ["-g"]:
        print(state.get("gid", "1000"))
    else:
        sys.exit(10)
elif name == "uname":
    mapping = {"-s": state.get("os", "Linux"), "-m": state.get("arch", "x86_64")}
    if len(args) == 1 and args[0] in mapping:
        print(mapping[args[0]])
    else:
        sys.exit(10)
elif name == "docker":
    if not args:
        sys.exit(10)
    if args[0] == "build":
        if state.get("build_fail"):
            print("fake build failure", file=sys.stderr)
            sys.exit(1)
        try:
            iid_index = args.index("--iidfile") + 1
            iid_file = Path(args[iid_index])
        except (ValueError, IndexError):
            print("missing --iidfile", file=sys.stderr)
            sys.exit(2)
        if state.get("bad_iid") == "short":
            iid_file.write_text("abc123\n")
        elif state.get("bad_iid") == "upper":
            iid_file.write_text("A" * 64 + "\n")
        elif state.get("bad_iid") == "empty":
            iid_file.write_text("\n")
        else:
            iid_file.write_text("sha256:" + state.get("iid", "a" * 64) + "\n")
    elif args[0] == "run":
        runs = 0
        try:
            with (root / "commands.jsonl").open() as existing:
                for line in existing:
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue
                    if entry and entry[0] == "docker" and len(entry) > 1 and entry[1] == "run":
                        runs += 1
        except OSError:
            runs = 1
        fail_at = state.get("run_fail_at")
        if isinstance(fail_at, int) and runs == fail_at:
            print(f"fake run failure at {runs}", file=sys.stderr)
            sys.exit(3)
        if state.get("run_fail") and runs == 1:
            print("fake run failure", file=sys.stderr)
            sys.exit(3)
        print(state.get("run_stdout", ""), end="")
    else:
        sys.exit(10)
elif name in ("sudo", "systemctl", "busctl", "curl", "wget", "apt-get", "pacman",
              "dnf", "zypper", "python", "python3", "openrazer", "AppImage"):
    print(f"tripwire: {name} must not run on the host", file=sys.stderr)
    sys.exit(99)
else:
    raise AssertionError(name)
"""


@dataclass
class PortableHarness:
    root: Path
    environment: dict[str, str]

    def configure(self, **changes: object) -> None:
        path = self.root / "state.json"
        state = json.loads(path.read_text())
        state.update(changes)
        path.write_text(json.dumps(state))

    def run(
        self, *arguments: str, script: Path | None = None
    ) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
        target = script if script is not None else SCRIPT
        result = subprocess.run(
            ["/bin/bash", str(target), *arguments],
            env=self.environment,
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


def _write_fake(path: Path) -> None:
    path.write_text(f"#!{sys.executable}\n{FAKE}")
    path.chmod(0o755)


def portable_harness(tmp_path: Path) -> PortableHarness:
    root = tmp_path / "portable-fake"
    root.mkdir(parents=True)
    bin_dir = root / "bin"
    bin_dir.mkdir()
    for command in (
        "docker",
        "id",
        "uname",
        "sudo",
        "systemctl",
        "busctl",
        "curl",
        "wget",
        "apt-get",
        "pacman",
        "dnf",
        "zypper",
        "python",
        "python3",
        "openrazer",
        "AppImage",
    ):
        _write_fake(bin_dir / command)
    for command in (
        "bash",
        "mkdir",
        "mktemp",
        "rm",
        "rmdir",
        "dirname",
        "grep",
        "cat",
        "chmod",
        "cp",
        "pwd",
        "sleep",
    ):
        executable = shutil.which(command)
        assert executable is not None, command
        (bin_dir / command).symlink_to(executable)
    (root / "state.json").write_text(
        json.dumps(
            {
                "uid": "1000",
                "gid": "1000",
                "os": "Linux",
                "arch": "x86_64",
                "iid": "b" * 64,
                "run_stdout": "",
            }
        )
    )
    (root / "commands.jsonl").write_text("")
    for name in ("home", "runner-temp", "tmpdir", "temporary"):
        (root / name).mkdir(parents=True)
    environment = {
        "PATH": str(bin_dir),
        "HOME": str(root / "home"),
        "TMPDIR": str(root / "tmpdir"),
        "RUNNER_TEMP": str(root / "runner-temp"),
        "FAKE_ROOT": str(root),
        "LC_ALL": "C",
    }
    return PortableHarness(root, environment)


def stage_repo_copy(tmp_path: Path, *, name: str = "repo with spaces") -> Path:
    dest = tmp_path / name
    target = dest / "buildpython/steps/appimage"
    target.mkdir(parents=True)
    (target / "Dockerfile.portable").write_bytes(DOCKERFILE.read_bytes())
    script_bytes = SCRIPT.read_bytes()
    (target / "portable-build.sh").write_bytes(script_bytes)
    (target / "portable-build.sh").chmod(0o755)
    (target / "portable-inner.sh").write_bytes(INNER.read_bytes())
    (target / "portable-inner.sh").chmod(0o755)
    (dest / "pyproject.toml").write_text('[project]\nname = "naga-control"\n', encoding="utf-8")
    return dest


def docker_commands(commands: list[list[str]], verb: str) -> list[list[str]]:
    return [c for c in commands if c and c[0] == "docker" and len(c) > 1 and c[1] == verb]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def apt_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    in_install = False
    for line in text.splitlines():
        stripped = line.strip()
        if "apt-get install" in stripped:
            in_install = True
            after = stripped.split("apt-get install", 1)[1]
            for part in after.replace("\\", " ").split():
                clean = part.strip().rstrip(";")
                if clean in ("-y", "--no-install-recommends", "&&", "\\", ""):
                    continue
                if clean.startswith("-") or "://" in clean or "/" in clean:
                    continue
                tokens.append(clean)
            continue
        if not in_install:
            continue
        if stripped.startswith(("RUN ", "FROM ", "ENV ", "CMD ")):
            in_install = False
            continue
        if "rm -rf" in stripped:
            in_install = False
            continue
        for part in stripped.replace("\\", " ").replace("&&", " ").split():
            clean = part.strip().rstrip("\\").rstrip(";")
            if clean in ("&&", "\\", "") or clean.startswith("-"):
                continue
            if "://" in clean or "/" in clean:
                continue
            tokens.append(clean)
    return [t for t in tokens if t and t != "\\"]


def run_fragments(text: str) -> list[str]:
    fragments: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("RUN "):
            if current:
                fragments.append("\n".join(current))
            current = [line[4:]]
        elif current and (line.startswith(" ") or line.startswith("\t")):
            current.append(line)
        elif current:
            fragments.append("\n".join(current))
            current = []
    if current:
        fragments.append("\n".join(current))
    return fragments
