"""Session installer fakes: closed-PATH dbus-send/sleep plus staging helpers."""

from __future__ import annotations

import sys
from pathlib import Path

FAKE_DBUS = r"""
import json
import os
import sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
root = Path(os.environ["FAKE_ROOT"])
try:
    os.fstat(9)
except OSError:
    pass
else:
    with (root / "fd9-leak.log").open("a") as leak:
        leak.write("dbus-send leaked FD9\n")
    print("Error org.freedesktop.DBus.Error.Failed: FD9 leaked", file=sys.stderr)
    sys.exit(97)
state = json.loads((root / "state.json").read_text())
with (root / "commands.jsonl").open("a") as log:
    log.write(json.dumps([name, *args]) + "\n")
raw = state.get("raw_marker", "FAKE-RAW-ERROR-9f3a")
def fail():
    print("Error org.freedesktop.DBus.Error.Failed: " + str(raw), file=sys.stderr)
    sys.exit(1)
def header():
    print("method return time=1 sender=fake -> destination=fake serial=1 reply_serial=2")
bus_available = state.get("bus_available", True)
exited_file = root / "session-exited"
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
        value = False if exited else True
        if exited:
            value = bool(state.get("after_unique_owner", False))
        header()
        print("   boolean true" if value else "   boolean false")
        sys.exit(0)
    if exited:
        value = bool(state.get("after_well_owner", False))
    else:
        if (root / "session-started").is_file():
            if "start_has_owner" in state:
                value = bool(state.get("start_has_owner", True))
            else:
                value = True
        else:
            value = bool(state.get("has_owner", False))
    header()
    print("   boolean true" if value else "   boolean false")
    sys.exit(0)
if method == "org.freedesktop.DBus.StartServiceByName":
    if not bus_available or state.get("start_fail", False):
        fail()
    if state.get("start_fail_once", False):
        state["start_fail_once"] = False
        (root / "state.json").write_text(json.dumps(state))
        fail()
    (root / "session-started").write_text("1\n")
    try:
        exited_file.unlink()
    except FileNotFoundError:
        pass
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
        print('   string "not-a-unique"')
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
    exited_file.write_text("1\n")
    if state.get("exit_fail", False):
        fail()
    header()
    sys.exit(0)
if method == "org.freedesktop.DBus.ReloadConfig":
    if not bus_available or state.get("reload_fail", False):
        fail()
    header()
    sys.exit(0)
fail()
"""

FAKE_SLEEP = """#!/bin/bash
if [ -e /proc/self/fd/9 ]; then
  printf '%s\\n' "sleep leaked FD9" >> "$FAKE_ROOT/fd9-leak.log"
  exit 97
fi
exit 0
"""


def stage_session_helper(fake_root: Path, checkout_script: Path) -> None:
    """Copy the real session helper next to a staged installer checkout."""
    source = Path(__file__).resolve().parents[1] / "scripts" / "session_service.sh"
    target = checkout_script.parent / "session_service.sh"
    target.write_text(source.read_text())
    target.chmod(0o755)


def session_state_defaults() -> dict[str, object]:
    return {
        "bus_available": True,
        "has_owner": False,
        "getowner": ":1.50",
        "after_unique_owner": False,
        "after_well_owner": False,
    }


if __name__ == "__main__":
    print(sys.argv[0])
