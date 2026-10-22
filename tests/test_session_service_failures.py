"""Failure-path session-service helper checks with closed-PATH fakes."""

from __future__ import annotations

from pathlib import Path

from tests.session_service_fakes import RAW_MARKER, dests_for, make_harness, methods


def test_start_failure_is_fixed_and_redacted(tmp_path: Path) -> None:
    fake = make_harness(tmp_path, {"start_fail": True})
    result = fake.run_cli("start")
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == "error: service start failed\n"
    assert RAW_MARKER not in result.stderr
    assert ":1." not in result.stderr


def test_start_owner_timeout_uses_bounded_poll(tmp_path: Path) -> None:
    fake = make_harness(tmp_path, {"has_owner": False, "start_has_owner": False})
    result = fake.run_cli("start")
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == "error: service start timed out\n"
    assert RAW_MARKER not in result.stderr
    sleeps = fake.sleep_calls()
    assert 1 <= len(sleeps) <= 30
    assert fake.attempts() == ""


def test_prepare_failure_prevents_exit(tmp_path: Path) -> None:
    fake = make_harness(tmp_path, {"has_owner": True, "prepare_fail": True})
    result = fake.run_cli("stop")
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == "error: service prepare failed\n"
    assert RAW_MARKER not in result.stderr
    assert ":1.50" not in result.stderr
    found = methods(fake.dbus_calls())
    assert "org.nagacontrol.Service1.PrepareShutdown" in found
    assert "org.nagacontrol.Service1.Exit" not in found
    assert "ReleaseAll" not in str(fake.dbus_calls())


def test_malformed_unique_fails_without_exit(tmp_path: Path) -> None:
    fake = make_harness(tmp_path, {"has_owner": True, "getowner": "malformed"})
    result = fake.run_cli("stop")
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == "error: service stop failed\n"
    found = methods(fake.dbus_calls())
    assert "org.nagacontrol.Service1.PrepareShutdown" not in found
    assert "org.nagacontrol.Service1.Exit" not in found


def test_exit_reply_failure_is_benign_when_verified(tmp_path: Path) -> None:
    fake = make_harness(
        tmp_path,
        {
            "has_owner": True,
            "getowner": ":1.77",
            "exit_fail": True,
            "after_unique_owner": False,
            "after_well_owner": False,
        },
    )
    result = fake.run_cli("stop")
    assert result.returncode == 0
    assert result.stdout == "inactive\n"
    found = methods(fake.dbus_calls())
    assert "org.nagacontrol.Service1.Exit" in found
    assert dests_for(fake.dbus_calls(), "org.nagacontrol.Service1.Exit") == [":1.77"]


def test_disconnect_fails_closed(tmp_path: Path) -> None:
    fake = make_harness(
        tmp_path,
        {"has_owner": True, "disconnect_after_exit": True},
    )
    result = fake.run_cli("stop")
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == "error: service stop timed out\n"
    assert "inactive" not in result.stdout
    assert RAW_MARKER not in result.stderr


def test_replacement_owner_fails_closed(tmp_path: Path) -> None:
    fake = make_harness(
        tmp_path,
        {
            "has_owner": True,
            "getowner": ":1.50",
            "after_unique_owner": False,
            "after_well_owner": True,
        },
    )
    result = fake.run_cli("stop")
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == "error: service stop timed out\n"
    assert RAW_MARKER not in result.stderr


def test_poll_timeout_when_names_remain(tmp_path: Path) -> None:
    fake = make_harness(
        tmp_path,
        {
            "has_owner": True,
            "getowner": ":1.50",
            "after_unique_owner": True,
            "after_well_owner": True,
        },
    )
    result = fake.run_cli("stop")
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == "error: service stop timed out\n"
    assert len(fake.sleep_calls()) >= 5


def test_restart_does_not_start_after_failed_stop(tmp_path: Path) -> None:
    fake = make_harness(tmp_path, {"has_owner": True, "prepare_fail": True})
    result = fake.run_cli("restart")
    assert result.returncode != 0
    assert result.stdout == ""
    found = methods(fake.dbus_calls())
    assert "org.freedesktop.DBus.StartServiceByName" not in found
    assert "org.nagacontrol.Service1.PrepareShutdown" in found


def test_reload_failure_is_fixed(tmp_path: Path) -> None:
    fake = make_harness(tmp_path, {"reload_fail": True})
    result = fake.run_cli("reload")
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == "error: session bus reload failed\n"
    assert RAW_MARKER not in result.stderr


def test_unknown_command_and_extra_args_fail(tmp_path: Path) -> None:
    fake = make_harness(tmp_path)
    result = fake.run_cli("frobnicate")
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "error: unknown command\n"
    result = fake.run_cli("status", "extra")
    assert result.returncode == 2
    assert result.stdout == ""
    assert fake.dbus_calls() == []
