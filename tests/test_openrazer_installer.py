"""Read-only defaults and explicit, conservatively activated package replacement."""

import os
import pty
from pathlib import Path

import pytest

from tests.openrazer_installer_fakes import PIN, ROLES, TAG, VERSION, harness, operation_name


@pytest.mark.parametrize(
    "arguments", [(), ("--check",), ("--check", "--yes"), ("--add-openrazer-group",)]
)
def test_check_and_default_are_read_only(tmp_path: Path, arguments: tuple[str, ...]) -> None:
    fake = harness(tmp_path)
    result, commands = fake.run(*arguments)
    assert result.returncode == 0, result.stderr
    assert "UNVERIFIED" in result.stdout
    assert "Host import discoverability" in result.stdout
    assert "still pending" in result.stdout
    assert not any(command[0] in {"curl", "sudo", "systemctl", "bsdtar"} for command in commands)


def test_known_stamp_is_inventory_not_hardware_acceptance(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    fake.configure(installed=dict.fromkeys(ROLES, VERSION), stamps=dict.fromkeys(ROLES, PIN))
    result, _ = fake.run("--check")
    assert result.returncode == 0, result.stderr
    assert "KNOWN PINNED COHORT" in result.stdout
    assert "not hardware acceptance" in result.stdout


def test_upstream_package_inventory_is_unverified_not_absent(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    fake.configure(installed={role.removesuffix("-local"): "3.12.1-1" for role in ROLES})
    result, commands = fake.run("--check")
    assert result.returncode == 0, result.stderr
    assert "installed openrazer-daemon 3.12.1-1" in result.stdout
    assert "UNVERIFIED" in result.stdout
    assert not any(command[0] in {"curl", "sudo", "systemctl"} for command in commands)


@pytest.mark.parametrize("cohort", ["older", "partial", "mixed", "unstamped", "other-source"])
def test_other_cohorts_are_honestly_unverified(tmp_path: Path, cohort: str) -> None:
    fake = harness(tmp_path)
    versions = dict.fromkeys(ROLES, VERSION)
    stamps = dict.fromkeys(ROLES, PIN)
    if cohort == "older":
        versions = dict.fromkeys(ROLES, "3.12.1.pr2904.fix1-1")
    elif cohort == "partial":
        versions.pop(ROLES[1])
    elif cohort == "mixed":
        versions[ROLES[0]] = "3.12.1.pr2904.fix1-1"
    elif cohort == "unstamped":
        stamps = {}
    else:
        stamps[ROLES[1]] = "a" * 40
    fake.configure(installed=versions, stamps=stamps)
    result, _ = fake.run("--check")
    assert result.returncode == 0, result.stderr
    assert "UNVERIFIED" in result.stdout
    assert "KNOWN PINNED COHORT" not in result.stdout


@pytest.mark.parametrize(
    "installed", [{}, dict.fromkeys(ROLES, "3.12.1.pr2904.fix1-1"), dict.fromkeys(ROLES, VERSION)]
)
def test_explicit_replacement_is_one_interactive_transaction(
    tmp_path: Path, installed: dict[str, str]
) -> None:
    fake = harness(tmp_path)
    same_cohort = installed == dict.fromkeys(ROLES, VERSION)
    fake.configure(installed=installed, stamps=dict.fromkeys(ROLES, PIN) if same_cohort else {})
    # Manifest order, not API order, defines the set; shuffled rows are fine.
    manifest = fake.remote / "openrazer-arch-packages.sha256"
    manifest.write_text("\n".join(reversed(manifest.read_text().splitlines())) + "\n")
    result, commands = fake.run("--yes", "--version", TAG)
    assert result.returncode == 0, result.stderr
    transaction = next(command for command in commands if command[:2] == ["sudo", "pacman"])
    assert transaction[2] == "-U"
    assert len(transaction[3:]) == 3
    assert all(VERSION in name for name in transaction[3:])
    assert not any(
        flag in transaction
        for flag in ("--needed", "--noconfirm", "--overwrite", "--nodeps", "--ask")
    )
    assert [command for command in commands if operation_name(command) == "systemctl"] == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "openrazer-daemon.service"],
    ]
    assert ["systemctl", "--user", "show", "--property=Version", "--value"] in commands
    assert "activation DEFERRED" in result.stdout
    assert "Reboot/re-login" in result.stdout
    assert not any("api.github.com" in item for command in commands for item in command)
    assert "even at the same version" in result.stdout
    if same_cohort:
        assert "KNOWN PINNED COHORT" in result.stdout


@pytest.mark.parametrize("host,venv", [("3.14", "3.12"), ("3.12", "3.14")])
def test_activated_venv_cannot_change_system_python_acceptance(
    tmp_path: Path, host: str, venv: str
) -> None:
    fake = harness(tmp_path)
    fake.configure(host_python=host, venv_python=venv)
    fake.environment["VIRTUAL_ENV"] = str(tmp_path / "different-minor-venv")
    result, commands = fake.run("--yes", "--version", TAG)
    assert (result.returncode == 0) == (host == "3.14"), result.stderr
    assert not any(command[0] in {"python", "python3"} for command in commands)
    assert any(command[0] == "system-python3" for command in commands)
    assert any(command[:2] == ["sudo", "pacman"] for command in commands) == (host == "3.14")
    if host != "3.14":
        assert "host Python outside package bounds: 3.12" in result.stderr


@pytest.mark.parametrize("consent", [False, True])
def test_group_requires_own_consent_and_uses_actual_user(tmp_path: Path, consent: bool) -> None:
    fake = harness(tmp_path)
    fake.configure(groups="users")
    arguments = ["--yes", "--version", TAG]
    if consent:
        arguments.append("--add-openrazer-group")
    result, commands = fake.run(*arguments)
    assert result.returncode == 0, result.stderr
    additions = [command for command in commands if command[:2] == ["sudo", "usermod"]]
    assert additions == (
        [["sudo", "usermod", "-aG", "openrazer", "desktop-user"]] if consent else []
    )
    assert "wrong-inherited-user" not in result.stdout


def test_env_one_does_not_promise_unattended_confirmation(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    fake.environment["NAGA_CONTROL_INSTALL_OPENRAZER"] = "1"
    result, commands = fake.run("--version", TAG)
    assert result.returncode != 0
    assert "summary confirmation requires a terminal" in result.stderr
    assert not any(operation_name(command) in {"curl", "sudo", "systemctl"} for command in commands)


@pytest.mark.parametrize("opt_in", ["flag", "environment"])
@pytest.mark.parametrize("reply", ["y", "n"])
def test_explicit_install_summary_consent(tmp_path: Path, opt_in: str, reply: str) -> None:
    fake = harness(tmp_path)
    arguments = ["--version", TAG]
    if opt_in == "flag":
        arguments.append("--install")
    else:
        fake.environment["NAGA_CONTROL_INSTALL_OPENRAZER"] = "1"
    master, slave = pty.openpty()
    try:
        os.write(master, (reply + "\n").encode())
        result, commands = fake.run(*arguments, input_fd=slave)
    finally:
        os.close(master)
        os.close(slave)
    assert (result.returncode == 0) == (reply == "y"), result.stderr
    assert any(command[:2] == ["sudo", "pacman"] for command in commands) == (reply == "y")
    if reply == "n":
        assert "declined" in result.stderr


def test_check_overrides_environment_opt_in(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    fake.environment["NAGA_CONTROL_INSTALL_OPENRAZER"] = "1"
    result, commands = fake.run("--check")
    assert result.returncode == 0, result.stderr
    assert not any(command[0] in {"curl", "sudo", "systemctl"} for command in commands)


def test_env_zero_is_hard_skip_even_with_yes(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    fake.environment["NAGA_CONTROL_INSTALL_OPENRAZER"] = "0"
    result, commands = fake.run("--yes")
    assert result.returncode == 0
    assert "hard skip" in result.stdout
    assert commands == []


@pytest.mark.parametrize("value", ["", "true", "2"])
def test_invalid_env_rejected(tmp_path: Path, value: str) -> None:
    fake = harness(tmp_path)
    fake.environment["NAGA_CONTROL_INSTALL_OPENRAZER"] = value
    result, commands = fake.run()
    assert result.returncode != 0
    assert "must be 0, 1, or unset" in result.stderr
    assert commands == []
