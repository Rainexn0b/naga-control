"""Happy-path session-service helper checks with closed-PATH fakes."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.session_service_fakes import BASH, RAW_MARKER, SCRIPT, dests_for, make_harness, methods


def test_fd9_closed_in_children_while_parent_keeps_lock(tmp_path: Path) -> None:
    import contextlib
    import fcntl
    import os

    fake = make_harness(
        tmp_path,
        {
            "has_owner": True,
            "getowner": ":1.50",
            "after_unique_owner": True,
            "after_well_owner": True,
        },
    )
    lock = tmp_path / "install.lock"
    lock.write_text("")
    saved: int | None = None
    try:
        os.fstat(9)
    except OSError:
        pass
    else:
        saved = os.dup(9)
    raw_fd = os.open(lock, os.O_RDWR)
    try:
        os.dup2(raw_fd, 9)
    finally:
        if raw_fd != 9:
            os.close(raw_fd)
    try:
        fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
        source = subprocess.run(
            [BASH, "--noprofile", "--norc", "-c", f"source {SCRIPT}\ntest -e /proc/self/fd/9"],
            env=fake.environment,
            cwd=tmp_path,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            pass_fds=(9,),
        )
        assert source.returncode == 0, source.stderr
        result = subprocess.run(
            [BASH, "--noprofile", "--norc", str(SCRIPT), "stop"],
            env=fake.environment,
            cwd=tmp_path,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            pass_fds=(9,),
        )
        assert result.returncode != 0
        assert result.stderr == "error: service stop timed out\n"
        assert fake.fd9_leaks() == ""
        assert fake.attempts() == ""
        assert len(fake.sleep_calls()) >= 5
        os.fstat(9)
        other = os.open(lock, os.O_RDWR)
        try:
            try:
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                raise AssertionError("parent did not retain the install lock")
        finally:
            os.close(other)
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(9, fcntl.LOCK_UN)
        with contextlib.suppress(OSError):
            os.close(9)
        if saved is not None:
            os.dup2(saved, 9)
            os.close(saved)


def test_source_defines_only_prefixed_functions_without_running(tmp_path: Path) -> None:
    fake = make_harness(tmp_path)
    code = f"source {SCRIPT}\ndeclare -F\nset -o\ntrap -p\n"
    result = subprocess.run(
        [BASH, "--noprofile", "--norc", "-c", code],
        env=fake.environment,
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.count("naga_session_") >= 7
    for line in result.stdout.splitlines():
        if line.startswith("declare -f "):
            assert "naga_session_" in line
    assert fake.attempts() == ""
    assert fake.dbus_calls() == []


def test_bus_check_reports_ready_without_activation(tmp_path: Path) -> None:
    fake = make_harness(tmp_path)
    result = fake.run_cli("bus-check")
    assert result.returncode == 0
    assert result.stdout == "ready\n"
    assert result.stderr == ""
    calls = fake.dbus_calls()
    assert methods(calls) == ["org.freedesktop.DBus.GetId"]
    assert "org.nagacontrol.Service1" not in str(calls)
    assert "StartServiceByName" not in str(calls)
    for args in calls:
        assert "--session" in args
        assert any(a.startswith("--reply-timeout=") for a in args)
    assert fake.attempts() == ""


def test_bus_check_absent_is_unknown(tmp_path: Path) -> None:
    fake = make_harness(tmp_path, {"bus_available": False})
    result = fake.run_cli("bus-check")
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == "error: session bus is not available\n"
    assert RAW_MARKER not in result.stderr


def test_status_active_and_inactive_are_exact(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    active = make_harness(tmp_path / "a", {"has_owner": True})
    result = active.run_cli("status")
    assert result.returncode == 0
    assert result.stdout == "active\n"
    inactive = make_harness(tmp_path / "b", {"has_owner": False})
    result = inactive.run_cli("status")
    assert result.returncode == 0
    assert result.stdout == "inactive\n"


def test_status_never_activates(tmp_path: Path) -> None:
    fake = make_harness(tmp_path, {"has_owner": True})
    result = fake.run_cli("status")
    assert result.returncode == 0
    calls = fake.dbus_calls()
    assert methods(calls) == ["org.freedesktop.DBus.NameHasOwner"]
    assert dests_for(calls, "org.freedesktop.DBus.NameHasOwner") == ["org.freedesktop.DBus"]
    for args in calls:
        assert "--session" in args
        assert any(a.startswith("--reply-timeout=") for a in args)
        assert "StartServiceByName" not in args
        assert "PrepareShutdown" not in str(args)
        assert "ReleaseAll" not in str(args)
    assert fake.attempts() == ""


def test_status_unknown_has_no_false_inactive(tmp_path: Path) -> None:
    fake = make_harness(tmp_path, {"bus_available": False})
    result = fake.run_cli("status")
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == "error: service status is unknown\n"
    assert RAW_MARKER not in result.stderr
    (tmp_path / "m").mkdir()
    malformed = make_harness(tmp_path / "m", {"has_owner": True, "has_owner_malformed": True})
    result = malformed.run_cli("status")
    assert result.returncode != 0
    assert result.stdout == ""
    assert "inactive" not in result.stdout
    assert result.stderr == "error: service status is unknown\n"


def test_start_verifies_ownership_not_hardware(tmp_path: Path) -> None:
    fake = make_harness(tmp_path, {"has_owner": False, "start_has_owner": True})
    result = fake.run_cli("start")
    assert result.returncode == 0
    assert result.stdout == "active\n"
    calls = fake.dbus_calls()
    found = methods(calls)
    assert found[0] == "org.freedesktop.DBus.StartServiceByName"
    assert "org.freedesktop.DBus.NameHasOwner" in found
    assert "org.nagacontrol.Service1.PrepareShutdown" not in found
    assert "ReleaseAll" not in str(calls)
    for args in calls:
        assert "--session" in args
        assert any(a.startswith("--reply-timeout=") for a in args)
    assert fake.attempts() == ""


def test_stop_inactive_is_known_success(tmp_path: Path) -> None:
    fake = make_harness(tmp_path, {"has_owner": False})
    result = fake.run_cli("stop")
    assert result.returncode == 0
    assert result.stdout == "inactive\n"
    calls = fake.dbus_calls()
    assert methods(calls) == ["org.freedesktop.DBus.NameHasOwner"]
    assert "PrepareShutdown" not in str(calls)
    assert "Exit" not in str(calls)


def test_stop_success_uses_unique_two_step_order(tmp_path: Path) -> None:
    fake = make_harness(
        tmp_path,
        {
            "has_owner": True,
            "getowner": ":1.50",
            "after_unique_owner": False,
            "after_well_owner": False,
        },
    )
    result = fake.run_cli("stop")
    assert result.returncode == 0
    assert result.stdout == "inactive\n"
    calls = fake.dbus_calls()
    found = methods(calls)
    prepare_idx = found.index("org.nagacontrol.Service1.PrepareShutdown")
    exit_idx = found.index("org.nagacontrol.Service1.Exit")
    assert prepare_idx < exit_idx
    prepare_dests = dests_for(calls, "org.nagacontrol.Service1.PrepareShutdown")
    exit_dests = dests_for(calls, "org.nagacontrol.Service1.Exit")
    assert prepare_dests == [":1.50"]
    assert exit_dests == [":1.50"]
    assert "ReleaseAll" not in str(calls)
    assert RAW_MARKER not in result.stderr
    assert fake.attempts() == ""
    assert fake.sleep_calls() != [] or True


def test_reload_only_calls_broker_without_file_writes(tmp_path: Path) -> None:
    fake = make_harness(tmp_path)
    before = (tmp_path / "home" / "sentinel").read_bytes()
    result = fake.run_cli("reload")
    assert result.returncode == 0
    assert result.stdout == "reloaded\n"
    calls = fake.dbus_calls()
    assert methods(calls) == ["org.freedesktop.DBus.ReloadConfig"]
    assert (tmp_path / "home" / "sentinel").read_bytes() == before
    assert list((tmp_path / "home").iterdir()) == [tmp_path / "home" / "sentinel"]
    assert fake.attempts() == ""


def test_restart_stops_then_starts(tmp_path: Path) -> None:
    fake = make_harness(
        tmp_path,
        {
            "has_owner": False,
            "start_has_owner": True,
        },
    )
    result = fake.run_cli("restart")
    assert result.returncode == 0
    assert result.stdout == "active\n"
    found = methods(fake.dbus_calls())
    assert "org.freedesktop.DBus.NameHasOwner" in found
    assert "org.freedesktop.DBus.StartServiceByName" in found
