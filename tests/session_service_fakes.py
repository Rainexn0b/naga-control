"""Closed-PATH fakes for the session-service helper."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "session_service.sh"
_bash = shutil.which("bash")
assert _bash is not None, "Bash is required for session-service tests"
BASH = str(Path(_bash).resolve())
PYTHON_BIN = sys.executable
RAW_MARKER = "FAKE-RAW-ERROR-9f3a"

TRIPWIRES = (
    "busctl",
    "systemctl",
    "gdbus",
    "qdbus",
    "python",
    "python3",
    "pgrep",
    "pkill",
    "killall",
    "kill",
    "ps",
    "pidof",
    "naga-control",
    "naga-control-service",
    "naga-control-gui",
)

FAKE_DBUS = """#!PYTHON_BIN
import json
import os
import sys
from pathlib import Path
root = Path(os.environ["FAKE_ROOT"])
try:
    os.fstat(9)
except OSError:
    pass
else:
    with (root / "fd9-leak.log").open("a") as leak:
        leak.write("dbus-send leaked FD9\\n")
    print("Error org.freedesktop.DBus.Error.Failed: FD9 leaked", file=sys.stderr)
    sys.exit(97)
state = json.loads((root / "state.json").read_text())
args = sys.argv[1:]
with (root / "dbus.jsonl").open("a") as log:
    log.write(json.dumps(args) + "\\n")
raw = state.get("raw_marker", "FAKE-RAW-ERROR-9f3a")
def fail():
    print("Error org.freedesktop.DBus.Error.Failed: " + raw, file=sys.stderr)
    sys.exit(1)
def header():
    print("method return time=1 sender=fake -> destination=fake serial=1 reply_serial=2")
bus_available = state.get("bus_available", True)
exited_file = root / "exited"
exited = exited_file.is_file()
dest = ""
method = ""
queried = ""
for arg in args:
    if arg.startswith("--dest="):
        dest = arg[len("--dest="):]
for arg in args:
    if arg in ("org.freedesktop.DBus.GetId", "org.freedesktop.DBus.NameHasOwner", "org.freedesktop.DBus.StartServiceByName", "org.freedesktop.DBus.GetNameOwner", "org.freedesktop.DBus.ReloadConfig"):
        method = arg
    elif arg in ("org.nagacontrol.Service1.PrepareShutdown", "org.nagacontrol.Service1.Exit"):
        method = arg
for arg in args:
    if arg.startswith("string:"):
        queried = arg[len("string:"):]
if method == "org.freedesktop.DBus.GetId":
    if not bus_available or state.get("getid_fail", False):
        fail()
    if state.get("getid_malformed", False):
        print("garbage without token")
        sys.exit(0)
    header()
    print('   string "fake-bus-id-123"')
    sys.exit(0)
if method == "org.freedesktop.DBus.NameHasOwner":
    if not bus_available:
        fail()
    if state.get("disconnect_after_exit", False) and exited:
        fail()
    if state.get("has_owner_malformed", False):
        print("garbage without token")
        sys.exit(0)
    if queried.startswith(":"):
        if exited:
            value = state.get("after_unique_owner", False)
        else:
            value = True
        header()
        print("   boolean true" if value else "   boolean false")
        sys.exit(0)
    if exited:
        value = state.get("after_well_owner", False)
    elif method == "org.freedesktop.DBus.NameHasOwner" and queried == "org.nagacontrol.Service1":
        # start polling uses a dedicated flag when present
        if "start_has_owner" in state and not exited and dest == "org.freedesktop.DBus":
            # only for start path; stop path uses has_owner
            # disambiguate by checking if StartServiceByName was called
            called = (root / "started").is_file()
            if called:
                value = state.get("start_has_owner", True)
            else:
                value = state.get("has_owner", False)
        else:
            value = state.get("has_owner", False)
    else:
        value = False
    header()
    print("   boolean true" if value else "   boolean false")
    sys.exit(0)
if method == "org.freedesktop.DBus.StartServiceByName":
    if not bus_available or state.get("start_fail", False):
        fail()
    (root / "started").write_text("1\\n")
    header()
    print("   uint32 2")
    sys.exit(0)
if method == "org.freedesktop.DBus.GetNameOwner":
    if not bus_available:
        fail()
    if not state.get("has_owner", False) and not exited:
        fail()
    spec = state.get("getowner", ":1.50")
    if spec == "fail":
        fail()
    if spec == "malformed":
        header()
        print("   string \\"not-a-unique\\"")
        sys.exit(0)
    header()
    print('   string "' + str(spec) + '"')
    sys.exit(0)
if method == "org.nagacontrol.Service1.PrepareShutdown":
    if not bus_available or state.get("prepare_fail", False):
        fail()
    header()
    sys.exit(0)
if method == "org.nagacontrol.Service1.Exit":
    exited_file.write_text("1\\n")
    if state.get("exit_fail", False):
        fail()
    header()
    sys.exit(0)
if method == "org.freedesktop.DBus.ReloadConfig":
    if not bus_available or state.get("reload_fail", False):
        fail()
    header()
    sys.exit(0)
# Unexpected method (e.g. ReleaseAll) is logged and fails closed.
fail()
"""

FAKE_SLEEP = """#!BASH
if [ -e /proc/self/fd/9 ]; then
  printf '%s\\n' "sleep leaked FD9" >> "$FAKE_ROOT/fd9-leak.log"
  exit 97
fi
printf '%s\\n' "$*" >> "$FAKE_SLEEP_LOG"
exit 0
"""

FAKE_TRIPWIRE = """#!BASH
printf '%s\\n' "${0##*/} $*" >> "$FAKE_ATTEMPTS"
exit 97
"""


@dataclass
class SessionHarness:
    root: Path
    environment: dict[str, str]

    def run_cli(self, *argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [BASH, "--noprofile", "--norc", str(SCRIPT), *argv],
            env=self.environment,
            cwd=self.root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def run_func(self, func: str) -> subprocess.CompletedProcess[str]:
        code = f"source {SCRIPT}\n{func}\n"
        return subprocess.run(
            [BASH, "--noprofile", "--norc", "-c", code],
            env=self.environment,
            cwd=self.root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def dbus_calls(self) -> list[list[str]]:
        path = self.root / "dbus.jsonl"
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line]

    def sleep_calls(self) -> list[str]:
        path = self.root / "sleep.log"
        if not path.is_file():
            return []
        return path.read_text().splitlines()

    def attempts(self) -> str:
        return (self.root / "attempts.log").read_text()

    def fd9_leaks(self) -> str:
        path = self.root / "fd9-leak.log"
        if not path.is_file():
            return ""
        return path.read_text()


def make_harness(tmp_path: Path, state: dict[str, object] | None = None) -> SessionHarness:
    merged: dict[str, object] = {
        "bus_available": True,
        "has_owner": False,
        "getowner": ":1.50",
        "raw_marker": RAW_MARKER,
    }
    if state:
        merged.update(state)
    binary = tmp_path / "bin"
    binary.mkdir(exist_ok=True)
    root = tmp_path
    (root / "state.json").write_text(json.dumps(merged))
    (root / "dbus.jsonl").write_text("")
    (root / "sleep.log").write_text("")
    (root / "attempts.log").write_text("")
    (root / "fd9-leak.log").write_text("")
    dbus_path = binary / "dbus-send"
    dbus_path.write_text(FAKE_DBUS.replace("PYTHON_BIN", PYTHON_BIN))
    dbus_path.chmod(0o755)
    sleep_path = binary / "sleep"
    sleep_path.write_text(FAKE_SLEEP.replace("BASH", BASH))
    sleep_path.chmod(0o755)
    for name in TRIPWIRES:
        trip = binary / name
        trip.write_text(FAKE_TRIPWIRE.replace("BASH", BASH))
        trip.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "sentinel").write_text("unchanged\n")
    env = {
        "PATH": str(binary),
        "HOME": str(home),
        "TMPDIR": str(tmp_path),
        "LC_ALL": "C",
        "FAKE_ROOT": str(root),
        "FAKE_SLEEP_LOG": str(root / "sleep.log"),
        "FAKE_ATTEMPTS": str(root / "attempts.log"),
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent-fake-bus",
    }
    return SessionHarness(root, env)


def methods(calls: list[list[str]]) -> list[str]:
    found: list[str] = []
    for args in calls:
        for arg in args:
            if arg.startswith("org.freedesktop.DBus.") or arg.startswith(
                "org.nagacontrol.Service1."
            ):
                found.append(arg)
                break
    return found


def dests_for(calls: list[list[str]], method: str) -> list[str]:
    result: list[str] = []
    for args in calls:
        if method in args:
            for arg in args:
                if arg.startswith("--dest="):
                    result.append(arg[len("--dest=") :])
    return result
