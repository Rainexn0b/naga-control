"""Closed-PATH session-uninstall fixtures: no systemctl, no real bus."""

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ".local/share/naga-control"
IMAGE = ".local/bin/naga-control.AppImage"
WRAPPER = ".local/bin/naga-control"
MODE = f"{STATE}/service-manager"
HELPER = f"{STATE}/session-service.sh"
ACTIVATION = ".local/share/dbus-1/services/org.nagacontrol.Service1.service"
GUI_AUTOSTART = ".config/autostart/org.nagacontrol.NagaControl.desktop"
SERVICE_AUTOSTART = ".config/autostart/org.nagacontrol.Service.desktop"
PROFILES = ".config/naga-control/profiles.toml"

FAKE_COMMON = r"""
import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

root = Path(os.environ["FAKE_ROOT"])
name, args = Path(sys.argv[0]).name, sys.argv[1:]
state = json.loads((root / "state.json").read_text())
with (root / "commands.jsonl").open("a") as log:
    log.write(json.dumps([name, *args]) + "\n")

if name in ("sudo", "dbus-send", "sleep"):
    try:
        os.fstat(9)
    except OSError:
        pass
    else:
        with (root / "fd9-leak.log").open("a") as leak:
            leak.write(name + " leaked FD9\n")
        print("Error: FD9 leaked", file=sys.stderr)
        sys.exit(97)
    if name == "sudo":
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
elif name == "dbus-send":
    with (root / "dbus.jsonl").open("a") as log:
        log.write(json.dumps(args) + "\n")
    raw = "FAKE-RAW"
    bus_available = state.get("bus_available", True)
    exited = (root / "exited").is_file()
    dest = ""
    method = ""
    queried = ""
    for arg in args:
        if arg.startswith("--dest="):
            dest = arg[len("--dest="):]
    for arg in args:
        if arg in ("org.freedesktop.DBus.GetId", "org.freedesktop.DBus.NameHasOwner",
                   "org.freedesktop.DBus.StartServiceByName", "org.freedesktop.DBus.GetNameOwner",
                   "org.freedesktop.DBus.ReloadConfig"):
            method = arg
        elif arg in ("org.nagacontrol.Service1.PrepareShutdown", "org.nagacontrol.Service1.Exit"):
            method = arg
    for arg in args:
        if arg.startswith("string:"):
            queried = arg[len("string:"):]
    def header():
        print("method return time=1 sender=fake -> destination=fake serial=1 reply_serial=2")
    if method == "org.freedesktop.DBus.GetId":
        if not bus_available:
            fail("bus")
        header()
        print('   string "fake-bus-id"')
    elif method == "org.freedesktop.DBus.NameHasOwner":
        if not bus_available:
            fail("bus")
        if state.get("disconnect_after_exit", False) and exited:
            fail("bus")
        if queried.startswith(":"):
            value = (not exited) or state.get("after_unique_owner", False)
            header()
            print("   boolean true" if value else "   boolean false")
        else:
            if exited:
                value = state.get("after_well_owner", False)
            else:
                called = (root / "started").is_file()
                if called and "start_has_owner" in state:
                    value = state.get("start_has_owner", True)
                else:
                    value = state.get("has_owner", False)
            header()
            print("   boolean true" if value else "   boolean false")
    elif method == "org.freedesktop.DBus.StartServiceByName":
        if not bus_available or state.get("start_fail", False):
            fail("start")
        (root / "started").write_text("1\n")
        header()
        print("   uint32 2")
    elif method == "org.freedesktop.DBus.GetNameOwner":
        if not bus_available:
            fail("bus")
        if not state.get("has_owner", False) and not exited:
            fail("owner")
        spec = state.get("getowner", ":1.50")
        if spec == "fail":
            fail("owner")
        if spec == "malformed":
            header()
            print('   string "not-a-unique"')
        else:
            header()
            print('   string "' + str(spec) + '"')
    elif method == "org.nagacontrol.Service1.PrepareShutdown":
        # Record whether the owned login entry was fenced Hidden=true
        # before any cleanup, without affecting the fakebus result.
        try:
            _xdg = os.environ.get("XDG_CONFIG_HOME", "")
            if _xdg.startswith("/"):
                _svc = Path(_xdg) / "autostart/org.nagacontrol.Service.desktop"
            else:
                _svc = root / "home/.config/autostart/org.nagacontrol.Service.desktop"
            _text = _svc.read_text() if _svc.is_file() and not _svc.is_symlink() else ""
            with (root / "prepare_hidden.log").open("a") as _obs:
                _obs.write("hidden\n" if "Hidden=true" in _text else "not-hidden\n")
        except Exception:
            pass
        if not bus_available or state.get("prepare_fail", False):
            fail("prepare")
        header()
    elif method == "org.nagacontrol.Service1.Exit":
        (root / "exited").write_text("1\n")
        if state.get("exit_fail", False):
            fail("exit")
        header()
    elif method == "org.freedesktop.DBus.ReloadConfig":
        # Support failing only the second reload (final flush after removal)
        # while letting the fence reload succeed.
        try:
            _count_path = root / "reload_count"
            _count = int(_count_path.read_text().strip() or "0") if _count_path.is_file() else 0
        except Exception:
            _count = 0
        try:
            _count_path.write_text(str(_count + 1) + "\n")
        except Exception:
            pass
        if not bus_available or state.get("reload_fail", False):
            fail("reload")
        if state.get("reload_fail_second", False) and (_count + 1) >= 2:
            fail("reload")
        header()
    else:
        fail("unexpected method")
elif name == "sleep":
    with (root / "sleep.log").open("a") as log:
        log.write(" ".join(args) + "\n")
elif name == "sudo":
    if args == ["rm", "-f", str(root / "udev-rules/70-naga-control.rules")]:
        if state.get("sudo_rm_failure"):
            fail("sudo rm")
        Path(args[-1]).unlink(missing_ok=True)
    else:
        assert args == ["udevadm", "control", "--reload"], args
        if state.get("udev_failure"):
            fail("udev reload")
elif name in ("rm", "rmdir", "mv"):
    paths = [Path(arg) for arg in args if not arg.startswith("-")]
    assert paths and all(p.is_absolute() and p.is_relative_to(root) for p in paths), args
    if str(paths[-1]) == state.get(name + "_failure"):
        fail(name)
    key = "SAFE_" + name.upper()
    sys.exit(subprocess.run([os.environ[key], *args], check=False).returncode)
else:
    raise AssertionError("forbidden executable attempted: " + name)
"""

FAKE_TRIPWIRE = """#!BASH
printf '%s\\n' "${0##*/} $*" >> "$FAKE_ATTEMPTS"
exit 97
"""


@dataclass
class SessionUninstallerHarness:
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

    def dbus_calls(self) -> list[list[str]]:
        path = self.root / "dbus.jsonl"
        return (
            [json.loads(line) for line in path.read_text().splitlines() if line]
            if path.exists()
            else []
        )

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

    def seed_session(self, *, has_owner: bool = True) -> dict[str, bytes]:
        contents: dict[str, bytes] = {}
        owned = [
            IMAGE,
            WRAPPER,
            f"{STATE}/installed-tag",
            MODE,
            HELPER,
            ACTIVATION,
            ".local/share/applications/org.nagacontrol.NagaControl.desktop",
            ".local/share/icons/hicolor/64x64/apps/org.nagacontrol.NagaControl.png",
            PROFILES,
        ]
        for relative in owned:
            path = self.home / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if relative == MODE:
                path.write_text("session\n")
            elif relative == ACTIVATION:
                path.write_text(
                    "[D-BUS Service]\nName=org.nagacontrol.Service1\n"
                    "Exec=/tmp/fake-launcher service\n"
                )
            elif relative == HELPER:
                path.write_text("installed helper placeholder\n")
            elif relative in (IMAGE, WRAPPER):
                path.write_text("#!/bin/sh\nexit 97\n")
                path.chmod(0o755)
            else:
                path.write_text("fixture: " + relative + "\n")
            contents[relative] = path.read_bytes()
        for rel, text in (
            (
                SERVICE_AUTOSTART,
                "[Desktop Entry]\nType=Application\nName=Naga\nExec=/tmp/x service\nX-NagaControl-Service=true\n",
            ),
            (
                GUI_AUTOSTART,
                "[Desktop Entry]\nType=Application\nName=Naga\nExec=/tmp/x --start-hidden\nX-NagaControl-Owned=true\n",
            ),
        ):
            path = self.home / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            contents[rel] = path.read_bytes()
        self.configure(has_owner=has_owner)
        return contents


def stage_session_uninstaller(root: Path) -> Path:
    script = root / "uninstall.sh"
    source = (ROOT / "scripts/uninstall.sh").read_text()
    assert source.count("/etc/udev/rules.d") == 1
    assert "# NAGA_SESSION_HELPER_REQUIRED" in source
    script.write_text(source.replace("/etc/udev/rules.d", str(root / "udev-rules")))
    sibling = root / "session_service.sh"
    sibling.write_text((ROOT / "scripts/session_service.sh").read_text())
    return script


def session_harness(
    tmp_path: Path, state: dict[str, object] | None = None
) -> SessionUninstallerHarness:
    import shutil as _shutil

    root = tmp_path / "session-uninstaller"
    (root / "home").mkdir(parents=True, mode=0o700)
    bin_dir = root / "bin"
    bin_dir.mkdir()
    merged: dict[str, object] = {"has_owner": True, "getowner": ":1.50"}
    if state:
        merged.update(state)
    (root / "state.json").write_text(json.dumps(merged))
    (root / "commands.jsonl").write_text("")
    (root / "dbus.jsonl").write_text("")
    (root / "sleep.log").write_text("")
    (root / "attempts.log").write_text("")
    (root / "fd9-leak.log").write_text("")
    (root / "prepare_hidden.log").write_text("")
    for command in ("id", "dbus-send", "sleep", "sudo", "udevadm", "rm", "rmdir", "mv"):
        path = bin_dir / command
        path.write_text(f"#!{sys.executable}\n{FAKE_COMMON}")
        path.chmod(0o755)
    bash_path = _shutil.which("bash")
    assert bash_path is not None
    # No systemctl/busctl in PATH proves session mode never requires them.
    # Python tripwires prove the uninstall never executes an interpreter.
    for name in ("python", "python3"):
        trip = bin_dir / name
        trip.write_text(FAKE_TRIPWIRE.replace("BASH", bash_path))
        trip.chmod(0o755)
    for command in ("dirname", "stat", "mkdir", "cat", "flock", "bash", "mktemp"):
        executable = _shutil.which(command)
        assert executable is not None
        (bin_dir / command).symlink_to(executable)
    environment = {
        "HOME": str(root / "home"),
        "PATH": str(bin_dir),
        "FAKE_ROOT": str(root),
        "FAKE_ATTEMPTS": str(root / "attempts.log"),
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent-fake-bus",
    }
    for command in ("rm", "rmdir", "mv"):
        executable = _shutil.which(command)
        assert executable is not None
        environment["SAFE_" + command.upper()] = executable
    return SessionUninstallerHarness(root, stage_session_uninstaller(root), environment)


def assert_session_retained(fake: SessionUninstallerHarness, contents: dict[str, bytes]) -> None:
    for relative, content in contents.items():
        assert (fake.home / relative).read_bytes() == content


def dbus_methods(calls: list[list[str]]) -> list[str]:
    found: list[str] = []
    for args in calls:
        for arg in args:
            if arg.startswith("org.freedesktop.DBus.") or arg.startswith(
                "org.nagacontrol.Service1."
            ):
                found.append(arg)
                break
    return found
