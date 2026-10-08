"""Closed-PATH uninstall fixtures: all mutations stay in the private fixture."""

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from naga_control.integration_cli import INTEGRATION_FILES

ROOT = Path(__file__).resolve().parents[1]
USER_ASSETS = tuple(item.user_path for item in INTEGRATION_FILES if item.user_path)
IMAGE = ".local/bin/naga-control.AppImage"
WRAPPER = ".local/bin/naga-control"
STATE = ".local/share/naga-control"
PROFILES = ".config/naga-control/profiles.toml"
OWNED = (IMAGE, WRAPPER, *USER_ASSETS, f"{STATE}/installed-tag")

FAKE = r"""
import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

root = Path(os.environ["FAKE_ROOT"])
name, args = Path(sys.argv[0]).name, sys.argv[1:]
state_path = root / "state.json"
state = json.loads(state_path.read_text())
with (root / "commands.jsonl").open("a") as log:
    log.write(json.dumps([name, *args]) + "\n")

if name in ("systemctl", "sudo"):
    try:
        os.fstat(9)
    except OSError:
        pass
    else:
        raise AssertionError("lock FD 9 leaked to service/privilege child")
    with (root / "home/.local/share/naga-control/install.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            raise AssertionError("parent did not retain the installer lock")

def fail(message):
    print("fake " + message + " failure", file=sys.stderr)
    sys.exit(1)

if name == "id":
    assert args == ["-u"], args
    print(state.get("uid", "1000"))
elif name == "systemctl":
    if args == ["--user", "show", "--property=Version", "--value"]:
        if state.get("manager_failure"):
            fail("user manager")
        print("fake systemd")
    elif len(args) == 5 and args[:3] == ["--user", "show", "naga-control.service"]:
        assert args[-1] == "--value", args
        prop = args[3].removeprefix("--property=")
        assert prop in ("ActiveState", "UnitFileState", "LoadState"), args
        if state.get("query_failure") == prop or (
            prop == "ActiveState" and state.get("query_failure_after_stop") and state.get("stopped")
        ):
            fail(prop + " query")
        print(state[prop])
    else:
        assert args in (["--user", "stop", "naga-control.service"],
                        ["--user", "disable", "naga-control.service"],
                        ["--user", "daemon-reload"]), args
        operation = args[1]
        if state.get("unit_failure") == operation:
            fail(operation)
        if operation == "stop":
            state["ActiveState"] = state.get("stop_state", "inactive")
            state["stopped"] = True
        elif operation == "disable":
            state["UnitFileState"] = "disabled"
            state["ActiveState"] = state.get("disable_state", state["ActiveState"])
        state_path.write_text(json.dumps(state))
elif name == "sudo":
    if args == ["rm", "-f", str(root / "udev-rules/70-naga-control.rules")]:
        if state.get("sudo_rm_failure"):
            fail("sudo rm")
        Path(args[-1]).unlink(missing_ok=True)
    else:
        assert args == ["udevadm", "control", "--reload"], args
        if state.get("udev_failure"):
            fail("udev reload")
elif name in ("rm", "rmdir"):
    paths = [Path(arg) for arg in args if not arg.startswith("-")]
    assert paths and all(path.is_absolute() and path.is_relative_to(root) for path in paths), args
    if str(paths[-1]) == state.get(name + "_failure"):
        fail(name)
    sys.exit(subprocess.run([os.environ["SAFE_" + name.upper()], *args], check=False).returncode)
else:
    raise AssertionError("forbidden executable attempted: " + name)
"""


@dataclass
class UninstallerHarness:
    root: Path
    script: Path
    environment: dict[str, str]

    @property
    def home(self) -> Path:
        return self.root / "home"

    @property
    def lock(self) -> Path:
        return self.home / STATE / "install.lock"

    @property
    def rule(self) -> Path:
        return self.root / "udev-rules/70-naga-control.rules"

    def configure(self, **changes: object) -> None:
        path = self.root / "state.json"
        state = json.loads(path.read_text())
        state.update(changes)
        path.write_text(json.dumps(state))

    def commands(self) -> list[list[str]]:
        path = self.root / "commands.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def run(
        self, *arguments: str, reply: str = ""
    ) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
        result = subprocess.run(
            ["/bin/bash", str(self.script), *arguments],
            env=self.environment,
            input=reply,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return result, self.commands()

    def seed(self, *, image: bool = True) -> dict[str, bytes]:
        contents: dict[str, bytes] = {}
        for relative in (*OWNED, PROFILES):
            if relative == IMAGE and not image:
                continue
            path = self.home / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture: " + relative + "\n")
            contents[relative] = path.read_bytes()
        return contents

    def backup(self, name: str = "rollback.abc123", *, marker: bool = True) -> Path:
        backup = self.home / STATE / name
        backup.mkdir(parents=True, exist_ok=True)
        for filename in ("naga-control.AppImage", "installed-tag", "image.sha256"):
            (backup / filename).write_text("backup fixture\n")
        if marker:
            (backup / "installer-backup").write_text("naga-control-installer-backup-v1\n")
        return backup


def stage_uninstaller(root: Path) -> Path:
    """Substitute the sole system destination before any invocation."""
    script = root / "uninstall.sh"
    source = (ROOT / "scripts/uninstall.sh").read_text()
    assert source.count("/etc/udev/rules.d") == 1
    script.write_text(source.replace("/etc/udev/rules.d", str(root / "udev-rules")))
    return script


def harness(tmp_path: Path, *, python: bool = False) -> UninstallerHarness:
    root = tmp_path / "uninstaller"
    (root / "home").mkdir(parents=True, mode=0o700)
    bin_dir = root / "bin"
    bin_dir.mkdir()
    state: dict[str, object] = {
        "ActiveState": "active",
        "UnitFileState": "enabled",
        "LoadState": "loaded",
    }
    (root / "state.json").write_text(json.dumps(state))
    commands = ["id", "systemctl", "sudo", "udevadm", "rm", "rmdir"]
    if python:
        commands += ["python", "python3"]
    for command in commands:
        path = bin_dir / command
        path.write_text(f"#!{sys.executable}\n{FAKE}")
        path.chmod(0o755)
    for command in ("dirname", "stat", "mkdir", "cat", "flock", "bash"):
        executable = shutil.which(command)
        assert executable is not None
        (bin_dir / command).symlink_to(executable)
    environment = {
        "HOME": str(root / "home"),
        "PATH": str(bin_dir),
        "FAKE_ROOT": str(root),
    }
    for command in ("rm", "rmdir"):
        executable = shutil.which(command)
        assert executable is not None
        environment["SAFE_" + command.upper()] = executable
    return UninstallerHarness(root, stage_uninstaller(root), environment)


def assert_retained(fake: UninstallerHarness, contents: dict[str, bytes]) -> None:
    for relative, content in contents.items():
        assert (fake.home / relative).read_bytes() == content


def assert_no_cleanup(commands: list[list[str]]) -> None:
    assert not any(command[0] in {"rm", "rmdir", "sudo"} for command in commands)
