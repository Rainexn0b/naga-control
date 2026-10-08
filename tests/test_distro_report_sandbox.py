"""Reporter cannot fetch, mutate, prompt, or touch live buses/devices in tests."""

import subprocess
from pathlib import Path

import pytest

from tests.distro_report_fakes import BASH, REPORTER, TRIPWIRES, fields, harness, snapshot


@pytest.mark.parametrize(
    "data",
    [
        b"ID=ubuntu\nVERSION_ID=22.04\n",
        b"ID=unknown\n",
        b"ID=$(sudo ignored || true)\n",
        b"ID=ubuntu\x00\n",
    ],
)
@pytest.mark.parametrize("home_state", ["readonly", "absent", "unset"])
def test_report_is_read_only_with_no_home_requirement(
    tmp_path: Path, data: bytes, home_state: str
) -> None:
    fake = harness(tmp_path, data)
    home = tmp_path / "home"
    if home_state == "readonly":
        (home / "keep").chmod(0o400)
        home.chmod(0o500)
    elif home_state == "absent":
        fake.environment["HOME"] = str(tmp_path / "not-created-home")
    else:
        del fake.environment["HOME"]
    before = snapshot(tmp_path)
    try:
        result = fake.run(strict=True)
        after = snapshot(tmp_path)
    finally:
        if home_state == "readonly":
            home.chmod(0o700)
            (home / "keep").chmod(0o600)
    assert result.returncode == 0 and result.stderr == ""
    assert before == after  # Includes file bytes/inodes/modes/times and directory entries.
    assert fake.attempts() == ""
    assert fake.uname_calls() == ["-s", "-m"]
    assert not list((tmp_path / "temporary").iterdir())
    assert not list(home.glob(".*"))
    assert "[y/N]" not in result.stdout + result.stderr


def test_installer_and_extraction_environment_never_become_consent(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    fake.environment.update(
        NAGA_CONTROL_INSTALL_OPENRAZER="1",
        NAGA_CONTROL_VERSION="hostile-ref",
        NAGA_CONTROL_FORCE_DOWNLOAD="1",
        APPIMAGE_EXTRACT_AND_RUN="1",
        USER="private-user",
        DBUS_SESSION_BUS_ADDRESS="unix:path=/private-bus",
        XDG_RUNTIME_DIR="/private-runtime",
        PYTHONPATH="/private-python",
    )
    before = snapshot(tmp_path)
    result = fake.run()
    assert result.returncode == 0 and result.stderr == ""
    assert snapshot(tmp_path) == before
    assert "private-" not in result.stdout and "hostile-ref" not in result.stdout
    assert fields(result.stdout)["Report status"] == "CONDITIONAL"
    assert fake.attempts() == ""


def test_no_public_environment_path_override(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    fake.environment.update(
        OS_RELEASE_PATH="/private-host-identity",
        NAGA_OS_RELEASE_PATH="/private-host-identity",
        DISTRO_REPORT_PATH="/private-host-identity",
        OS_RELEASE_FILE="/private-host-identity",
    )
    result = fake.run(
        seams=False,
        entry='printf \'%s\\n\' "$(_dr_etc_path)" "$(_dr_vendor_path)"',
    )
    assert result.returncode == 0 and result.stderr == ""
    assert result.stdout == "/etc/os-release\n/usr/lib/os-release\n"
    assert fake.uname_calls() == []


def test_sourcing_guard_does_not_run_report_or_inspect_live_identity(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    result = fake.run(seams=False, entry=":", strict=True)
    assert result.returncode == 0 and result.stdout == result.stderr == ""
    assert fake.uname_calls() == []


def test_help_is_only_accepted_option_and_needs_no_tools_or_identity(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    fake.environment["PATH"] = str(tmp_path / "empty-not-created-bin")
    fake.etc.unlink()
    before = snapshot(tmp_path)
    result = subprocess.run(
        [BASH, "--noprofile", "--norc", str(REPORTER), "--help"],
        env=fake.environment,
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0 and result.stderr == ""
    assert "usage: bash scripts/distro_report.sh [--help]" in result.stdout
    assert "CRLF" in result.stdout and "without newline" in result.stdout
    assert "No host Python required" in result.stdout
    assert snapshot(tmp_path) == before and fake.attempts() == ""
    assert fake.uname_calls() == []


@pytest.mark.parametrize(
    "arguments",
    [
        ("--json",),
        ("--check",),
        ("-h",),
        ("--help", "extra"),
        ("--path", "/private/identity"),
        ("--install",),
        ("--",),
        ("private-hostile-argument",),
    ],
)
def test_invalid_arguments_fail_without_host_facts_or_echoing_raw_arguments(
    tmp_path: Path, arguments: tuple[str, ...]
) -> None:
    fake = harness(tmp_path)
    before = snapshot(tmp_path)
    result = subprocess.run(
        [BASH, "--noprofile", "--norc", str(REPORTER), *arguments],
        env=fake.environment,
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 2 and result.stdout == ""
    assert result.stderr == "error: only --help or no arguments are accepted\n"
    assert "private" not in result.stderr
    assert snapshot(tmp_path) == before and fake.attempts() == ""
    assert fake.uname_calls() == []


@pytest.mark.parametrize("empty_path", [False, True])
def test_missing_uname_reports_unknown_without_any_fallback_query(
    tmp_path: Path, empty_path: bool
) -> None:
    fake = harness(tmp_path)
    if empty_path:
        fake.environment["PATH"] = str(tmp_path / "missing-bin")
    else:
        (tmp_path / "bin/uname").unlink()
    before = snapshot(tmp_path)
    result = fake.run()
    report = fields(result.stdout)
    assert result.returncode == 0 and result.stderr == ""
    assert report["OS"] == report["Architecture"] == report["Report status"] == "UNKNOWN"
    assert snapshot(tmp_path) == before and fake.attempts() == ""
    assert fake.uname_calls() == []


def test_persistent_tripwires_detect_swallowed_failures(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    # Validate the test instrumentation itself: || true must not erase attempts.
    result = subprocess.run(
        [BASH, "--noprofile", "--norc", "-c", "curl ignored || true; python3 ignored || true"],
        env=fake.environment,
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0
    assert fake.attempts().splitlines() == ["curl ignored", "python3 ignored"]
    assert "sudo" in TRIPWIRES and "ldd" in TRIPWIRES and "openrazer-daemon" in TRIPWIRES


def test_device_path_tripwire_is_active_without_reading_a_device(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    # DEBUG catches the command before redirection can open any live path.
    with pytest.raises(AssertionError, match="forbidden live device/bus path attempt"):
        fake.run(entry=": < /dev/uinput")
    assert fake.attempts().splitlines() == ["forbidden live device/bus path attempt"]


def test_fixture_data_cannot_replace_closed_path_or_call_helper(tmp_path: Path) -> None:
    fake = harness(
        tmp_path,
        b"""PATH=/usr/bin:/bin
LD_PRELOAD=not-a-library
BASH_ENV=$(curl ignored)
NAGA_CONTROL_INSTALL_OPENRAZER=1
IGNORE=$(openrazer-daemon ignored || true)
IGNORE2=`Naga-Control-x86_64.AppImage ignored`
ID=ubuntu
VERSION_ID=22.04
""",
    )
    before = snapshot(tmp_path)
    result = fake.run(strict=True)
    assert result.returncode == 0 and result.stderr == ""
    assert fields(result.stdout)["Report status"] == "CONDITIONAL"
    assert fake.uname_calls() == ["-s", "-m"]
    assert snapshot(tmp_path) == before
