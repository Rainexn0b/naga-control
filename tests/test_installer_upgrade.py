"""Consent, atomic images, rollback and conservative opt-in activation."""

import json
import os
import pty
from pathlib import Path

import pytest

from tests.installer_app_fakes import (
    ASSET,
    HELPER_OK,
    PREVIOUS_TAG,
    USER_FILES,
    app_harness,
    assert_private_cleanup,
    installed_image,
    mutations,
    seed_previous,
    stamp,
)
from tests.openrazer_installer_fakes import ROOT, TAG


@pytest.mark.parametrize("consent", ["yes", "no", "nonTTY", "flag"])
def test_active_service_requires_consent_before_stop_or_replacement(
    tmp_path: Path, consent: str
) -> None:
    fake, script = app_harness(tmp_path)
    previous = seed_previous(fake)
    inode = installed_image(fake).stat().st_ino
    arguments = ["--version", TAG]
    if consent == "flag":
        arguments.append("--restart-service")
    master = slave = None
    try:
        if consent in {"yes", "no"}:
            master, slave = pty.openpty()
            os.write(master, ("y\n" if consent == "yes" else "n\n").encode())
        result, commands = fake.run(*arguments, script=script, input_fd=slave)
    finally:
        if master is not None and slave is not None:
            os.close(master)
            os.close(slave)
    approved = consent in {"yes", "flag"}
    assert (result.returncode == 0) == approved, result.stderr
    assert (["systemctl", "--user", "stop", "naga-control.service"] in commands) == approved
    assert "remapping" in result.stdout
    if not approved:
        assert "canceled" in result.stderr
        assert mutations(commands) == []
        assert installed_image(fake).read_bytes() == previous
        assert installed_image(fake).stat().st_ino == inode
        assert stamp(fake).read_text() == PREVIOUS_TAG + "\n"
    assert_private_cleanup(fake)


@pytest.mark.parametrize("failure", ["stop", "active", "deactivating", "failed"])
def test_stop_failure_or_unfinished_job_never_replaces_image(tmp_path: Path, failure: str) -> None:
    fake, script = app_harness(tmp_path)
    previous = seed_previous(fake)
    if failure == "stop":
        fake.configure(unit_failure="stop")
    else:
        fake.configure(stop_state=failure)
    result, commands = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode != 0
    assert "stop" in result.stderr
    assert installed_image(fake).read_bytes() == previous
    assert stamp(fake).read_text() == PREVIOUS_TAG + "\n"
    assert not any(c[0] in {"sudo", ASSET} for c in commands)
    assert not any(c[0] == "systemctl" and c[2] in {"start", "enable"} for c in commands)
    assert_private_cleanup(fake)


def test_atomic_upgrade_retains_verified_backup_pair_and_old_inode(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    previous = seed_previous(fake)
    image = installed_image(fake)
    inode = image.stat().st_ino
    profile = fake.root / "home/.config/naga-control/profiles.toml"
    profile.parent.mkdir(parents=True)
    profile.write_text("user profile untouched\n")
    with image.open("rb") as old_inode:
        result, commands = fake.run("--version", TAG, "--restart-service", script=script)
        assert old_inode.read() == previous
    assert result.returncode == 0, result.stderr
    assert image.stat().st_ino != inode
    assert image.read_bytes() == (fake.remote / ASSET).read_bytes()
    backups = list(stamp(fake).parent.glob("rollback.*"))
    assert len(backups) == 1
    assert (backups[0] / "naga-control.AppImage").read_bytes() == previous
    assert (backups[0] / "installed-tag").read_text() == PREVIOUS_TAG + "\n"
    assert (backups[0] / "image.sha256").is_file()
    assert "keeping newest verified rollback" in result.stdout
    assert profile.read_text() == "user profile untouched\n"
    stop = commands.index(["systemctl", "--user", "stop", "naga-control.service"])
    assert all(i < stop for i, c in enumerate(commands) if c[0] == "curl")
    assert "NOT proof of hardware readiness" in result.stdout
    assert sum("GetSnapshot" in line for line in result.stdout.splitlines()) == 1
    assert [c for c in commands if c[0] == "busctl"] == [["busctl", "--user", "status"]]
    assert not any("trigger" in c for c in commands)
    assert_private_cleanup(fake)


def test_unchanged_reinstall_preserves_backup_and_force_creates_pair(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    seed_previous(fake)
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    backups = list(stamp(fake).parent.glob("rollback.*"))
    assert len(backups) == 1
    assert "keeping newest verified rollback" in result.stdout
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    assert list(stamp(fake).parent.glob("rollback.*")) == backups
    assert "keeping newest verified rollback" in result.stdout
    fake.environment["NAGA_CONTROL_FORCE_DOWNLOAD"] = "1"
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    kept = list(stamp(fake).parent.glob("rollback.*"))
    assert len(kept) == 1
    assert "keeping newest verified rollback" in result.stdout
    assert "removed older verified rollback" in result.stdout
    assert (kept[0] / "installed-tag").read_text() == TAG + "\n"
    assert_private_cleanup(fake)


@pytest.mark.parametrize("failure", ["integration", "daemon-reload", "enable"])
def test_app_only_failure_restores_previous_files_and_resumes_safely(
    tmp_path: Path, failure: str
) -> None:
    fake, script = app_harness(tmp_path)
    previous = seed_previous(fake)
    if failure == "integration":
        fake.configure(integration_failure=1)
    else:
        fake.configure(unit_failure=failure, unit_failure_once=True)
    result, commands = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode != 0
    assert "failed" in result.stderr
    assert installed_image(fake).read_bytes() == previous
    assert stamp(fake).read_text() == PREVIOUS_TAG + "\n"
    for relative in USER_FILES:
        assert (fake.root / "home" / relative).read_text() == "previous integration\n"
    assert ["systemctl", "--user", "start", "naga-control.service"] in commands
    assert "app installed;" not in result.stdout
    assert_private_cleanup(fake)


def test_rollback_restoration_failure_is_distinct_not_success(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    seed_previous(fake)
    fake.configure(unit_failure="daemon-reload")
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode != 0
    assert "RESTORATION FAILED" in result.stderr
    assert "app installed;" not in result.stdout
    assert_private_cleanup(fake)


@pytest.mark.parametrize("previous_state", ["enabled", "enabled-runtime", "disabled"])
def test_rollback_restores_unit_enable_state(tmp_path: Path, previous_state: str) -> None:
    fake, script = app_harness(tmp_path)
    seed_previous(fake)
    fake.configure(unit_state=previous_state, unit_failure="enable", unit_failure_once=True)
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode != 0
    assert json.loads((fake.root / "state.json").read_text())["unit_state"] == previous_state
    assert_private_cleanup(fake)


def test_uninstall_only_removes_marked_installer_backups_and_keeps_lock(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    seed_previous(fake)
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    state_dir = stamp(fake).parent
    backup = next(state_dir.glob("rollback.*"))
    lock = state_dir / "install.lock"
    inode = lock.stat().st_ino
    unrelated = state_dir / "rollback.abcdef"
    unrelated.mkdir()
    (unrelated / "naga-control.AppImage").write_text("not installer-owned\n")
    uninstall = fake.root / "uninstall.sh"
    uninstall.write_text(
        (ROOT / "scripts/uninstall.sh")
        .read_text()
        .replace("/etc/udev/rules.d", str(fake.root / "missing-udev-rules"))
    )
    result, commands = fake.run("--yes", script=uninstall)
    assert result.returncode == 0, result.stderr
    assert not backup.exists()
    assert not stamp(fake).exists()
    assert (unrelated / "naga-control.AppImage").read_text() == "not installer-owned\n"
    assert lock.stat().st_ino == inode
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)


@pytest.mark.parametrize("failure", ["helper", "integration", "enable"])
def test_opt_in_partial_failure_stays_stopped_and_never_activates(
    tmp_path: Path, failure: str
) -> None:
    fake, script = app_harness(tmp_path, helper=HELPER_OK)
    previous = seed_previous(fake)
    if failure == "helper":
        fake.configure(helper_install_failure=42)
    elif failure == "integration":
        fake.configure(integration_failure=1)
    elif failure == "enable":
        fake.configure(unit_failure="enable", unit_failure_once=True)
    result, commands = fake.run(
        "--version", TAG, "--restart-service", "--install-openrazer", script=script
    )
    assert result.returncode != 0
    assert "remains stopped" in result.stderr + result.stdout
    assert ["installer-helper", "--version", TAG, "--preflight"] in commands
    assert ["installer-helper", "--version", TAG, "--install"] in commands
    assert installed_image(fake).read_bytes() == previous
    assert stamp(fake).read_text() == PREVIOUS_TAG + "\n"
    assert not any("--now" in c or (c[0] == "systemctl" and c[2] == "start") for c in commands)
    assert "installation staged:" not in result.stdout
    assert_private_cleanup(fake)


def test_real_helper_transaction_failure_after_preflight_keeps_previous_naga_stopped(
    tmp_path: Path,
) -> None:
    fake, script = app_harness(tmp_path)
    previous = seed_previous(fake)
    fake.stage_openrazer(script.parent / "install_openrazer.sh")
    fake.configure(pacman_failure=1)
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n")
        result, commands = fake.run(
            "--version",
            TAG,
            "--restart-service",
            "--install-openrazer",
            script=script,
            input_fd=slave,
        )
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode != 0
    assert "Read-only install preflight passed" in result.stdout
    assert "pacman transaction failed" in result.stderr
    assert "Naga remains stopped" in result.stderr
    assert installed_image(fake).read_bytes() == previous
    assert stamp(fake).read_text() == PREVIOUS_TAG + "\n"
    for relative in USER_FILES:
        assert (fake.root / "home" / relative).read_text() == "previous integration\n"
    assert json.loads((fake.root / "state.json").read_text())["service_state"] == "inactive"
    stop = commands.index(["systemctl", "--user", "stop", "naga-control.service"])
    transaction = next(i for i, c in enumerate(commands) if c[:2] == ["sudo", "pacman"])
    assert stop < transaction
    assert mutations(commands) == [commands[stop], commands[transaction]]
    assert "installation staged:" not in result.stdout and "app installed;" not in result.stdout
    assert_private_cleanup(fake)


def test_opt_in_success_only_enables_and_pending_udev_is_not_ready(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path, helper=HELPER_OK)
    seed_previous(fake)
    result, commands = fake.run(
        "--version", TAG, "--restart-service", "--install-openrazer", script=script
    )
    assert result.returncode == 0, result.stderr
    assert ["systemctl", "--user", "enable", "naga-control.service"] in commands
    assert not any("--now" in c or "restart" in c for c in commands)
    assert "installation staged:" in result.stdout
    assert "service running" not in result.stdout
    fake.configure(udev_failure=1)
    (fake.root / "commands.jsonl").unlink()
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "udev reload failed" in result.stdout
    assert "installation staged:" in result.stdout
    assert "service running" not in result.stdout
    assert not any("--now" in c or "trigger" in c for c in commands)
    assert_private_cleanup(fake)
