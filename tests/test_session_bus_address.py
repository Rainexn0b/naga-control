"""Session bus address guard: fail closed before any dbus-send on missing/autolaunch."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.session_service_fakes import RAW_MARKER, make_harness

VERBS: tuple[str, ...] = ("bus-check", "status", "start", "stop", "restart", "reload")

# None means the variable is unset entirely.
ADDRESSES: tuple[tuple[str, str | None], ...] = (
    ("unset", None),
    ("empty", ""),
    ("autolaunch-bare", "autolaunch:"),
    ("autolaunch-scoped", "autolaunch:scope=*"),
    ("fallback-leading", "autolaunch:;unix:path=/fake-bus"),
    ("fallback-trailing", "unix:path=/fake-bus;autolaunch:"),
    ("fallback-scoped-middle", "unix:path=/fake-bus;autolaunch:scope=*;unix:path=/other"),
)

FIXED_ERROR = "error: session bus is not available\n"


@pytest.mark.parametrize("verb", VERBS)
@pytest.mark.parametrize("label,address", ADDRESSES)
def test_guarded_address_rejects_before_dbus(
    tmp_path: Path, verb: str, label: str, address: str | None
) -> None:
    del label
    fake = make_harness(tmp_path)
    if address is None:
        fake.environment.pop("DBUS_SESSION_BUS_ADDRESS", None)
    else:
        fake.environment["DBUS_SESSION_BUS_ADDRESS"] = address
    result = fake.run_cli(verb)
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == FIXED_ERROR
    assert RAW_MARKER not in result.stderr
    assert "autolaunch" not in result.stderr
    assert "unix:" not in result.stderr
    assert "/fake" not in result.stderr
    assert fake.dbus_calls() == []
    assert fake.sleep_calls() == []
    assert fake.attempts() == ""
    assert fake.fd9_leaks() == ""


def test_explicit_address_still_reaches_bus(tmp_path: Path) -> None:
    fake = make_harness(tmp_path)
    assert fake.environment["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/nonexistent-fake-bus"
    result = fake.run_cli("bus-check")
    assert result.returncode == 0
    assert result.stdout == "ready\n"
    assert fake.dbus_calls() != []


def test_source_with_guarded_address_has_no_effects(tmp_path: Path) -> None:
    import subprocess

    from tests.session_service_fakes import BASH, SCRIPT

    fake = make_harness(tmp_path)
    fake.environment["DBUS_SESSION_BUS_ADDRESS"] = "autolaunch:"
    code = f"source {SCRIPT}\ndeclare -F\n"
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
    assert "naga_session__check_bus_address" in result.stdout
    assert fake.dbus_calls() == []
    assert fake.attempts() == ""
