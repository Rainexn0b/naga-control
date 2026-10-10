"""Unverified previous images never block a verified upgrade; they quarantine."""

import hashlib
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
    quarantines,
    rollbacks,
    seed_altered_previous,
    seed_previous,
    stamp,
)
from tests.openrazer_installer_fakes import ROOT, TAG, InstallerHarness


def _quarantine_ok(fake: InstallerHarness, altered: bytes, tag: str) -> Path:
    kept = quarantines(fake)
    assert len(kept) == 1
    assert (kept[0] / "naga-control.AppImage").read_bytes() == altered
    assert (kept[0] / "installed-tag").read_text() == tag + "\n"
    marker = (kept[0] / "quarantine").read_text()
    assert marker.startswith("naga-control-installer-quarantine-v1\nUNVERIFIED")
    assert not (kept[0] / "image.sha256").exists()
    assert not (kept[0] / "installer-backup").exists()
    assert rollbacks(fake) == []
    assert not list((fake.root / "home").rglob(".quarantine.*"))
    return kept[0]


@pytest.mark.parametrize("active", [True, False])
def test_altered_old_upgrades_with_quarantine(tmp_path: Path, active: bool) -> None:
    fake, script = app_harness(tmp_path)
    _, altered = seed_altered_previous(fake, active=active)
    profile = fake.root / "home/.config/naga-control/profiles.toml"
    profile.parent.mkdir(parents=True)
    profile.write_text("user profile untouched\n")
    image = installed_image(fake)
    inode = image.stat().st_ino
    with image.open("rb") as old_inode:
        args = ["--version", TAG]
        if active:
            args.append("--restart-service")
        result, commands = fake.run(*args, script=script)
        assert old_inode.read() == altered
    assert result.returncode == 0, result.stderr
    assert "warning" in result.stdout and "quarantine" in result.stdout
    assert "mismatch" in result.stdout or "checksum" in result.stdout
    assert "held until successful commit then removed" in result.stdout
    assert "removed unverified quarantine" in result.stdout
    assert image.stat().st_ino != inode
    assert image.read_bytes() == (fake.remote / ASSET).read_bytes()
    assert stamp(fake).read_text() == TAG + "\n"
    assert profile.read_text() == "user profile untouched\n"
    assert quarantines(fake) == []
    assert rollbacks(fake) == []
    # New bytes were strictly verified before any stop/privilege/execution.
    stop = (
        commands.index(["systemctl", "--user", "stop", "naga-control.service"]) if active else None
    )
    curls = [i for i, c in enumerate(commands) if c[0] == "curl"]
    assert curls
    if stop is not None:
        assert all(i < stop for i in curls)
    assert not any(c[0] == ASSET and c[1] == "--uninstall" for c in commands)
    assert "app installed;" in result.stdout or "installation staged:" in result.stdout
    assert_private_cleanup(fake)


def test_explicit_v04_to_v05_repro(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    old = (fake.remote / ASSET).read_bytes()
    image = installed_image(fake)
    image.parent.mkdir(parents=True)
    image.write_bytes(old)
    image.chmod(0o755)
    stamp(fake).parent.mkdir(parents=True)
    stamp(fake).write_text("v0.4.0\n")
    for relative in USER_FILES:
        target = fake.root / "home" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("previous integration\n")
    fake.remote.joinpath(ASSET).write_bytes(old + b"\n# v0.5.0 fixture\n")
    fake.configure(previous_tag="v0.4.0", previous_digest=hashlib.sha256(old).hexdigest())
    fake.remote.joinpath(ASSET + ".sha256").write_text(
        hashlib.sha256(fake.remote.joinpath(ASSET).read_bytes()).hexdigest() + "  " + ASSET + "\n"
    )
    fake.configure(service_state="active", unit_state="enabled")
    # Local rebuild of the installed v0.4.0 image.
    altered = old + b"\n# locally rebuilt v0.4.0\n"
    image.write_bytes(altered)
    inode = image.stat().st_ino
    result, _ = fake.run("--version", "v0.5.0", "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    assert image.stat().st_ino != inode
    assert image.read_bytes() == (fake.remote / ASSET).read_bytes()
    assert stamp(fake).read_text() == "v0.5.0\n"
    assert "held until successful commit then removed" in result.stdout
    assert "removed unverified quarantine" in result.stdout
    assert quarantines(fake) == []
    assert rollbacks(fake) == []
    assert_private_cleanup(fake)


@pytest.mark.parametrize(
    "problem",
    ["new-malformed", "new-tampered", "new-missing-checksum", "new-download-error"],
)
def test_unverified_old_new_failures_leave_everything_untouched(
    tmp_path: Path, problem: str
) -> None:
    fake, script = app_harness(tmp_path, helper=HELPER_OK)
    _, altered = seed_altered_previous(fake, active=True)
    image = installed_image(fake)
    inode = image.stat().st_ino
    manifest = fake.remote / (ASSET + ".sha256")
    row = manifest.read_text()
    if problem == "new-malformed":
        manifest.write_text("z" + row[1:])
    elif problem == "new-tampered":
        (fake.remote / ASSET).write_bytes(b"tampered-new")
    elif problem == "new-missing-checksum":
        manifest.unlink()
    else:
        fake.configure(download_fail=[ASSET])
    result, commands = fake.run(
        "--version", TAG, "--install-openrazer", "--restart-service", script=script
    )
    assert result.returncode != 0
    assert "fake prerequisite" not in result.stdout
    assert not any(c[0] == "installer-helper" for c in commands)
    assert mutations(commands) == []
    assert not any(c[0] in {"sudo", ASSET} for c in commands)
    assert image.stat().st_ino == inode
    assert image.read_bytes() == altered
    assert stamp(fake).read_text() == PREVIOUS_TAG + "\n"
    for relative in USER_FILES:
        assert (fake.root / "home" / relative).read_text() == "previous integration\n"
    assert quarantines(fake) == []
    assert "app installed;" not in result.stdout
    assert_private_cleanup(fake)


def test_old_checksum_unavailable_still_upgrades_verified(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    seed_altered_previous(fake, active=False)
    fake.configure(previous_checksum_unavailable=True)
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "checksum unavailable" in result.stdout
    assert "quarantine" in result.stdout
    assert "removed unverified quarantine" in result.stdout
    assert installed_image(fake).read_bytes() == (fake.remote / ASSET).read_bytes()
    assert stamp(fake).read_text() == TAG + "\n"
    assert quarantines(fake) == []
    assert rollbacks(fake) == []
    # No unchecked fallback: the new sidecar was still strictly fetched.
    assert any(c[0] == "curl" and c[-1].endswith(f"/{TAG}/{ASSET}.sha256") for c in commands)
    assert_private_cleanup(fake)


def test_old_malformed_sidecar_still_upgrades_verified(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    seed_altered_previous(fake, active=False)
    fake.configure(previous_checksum_text="not-a-valid-row\n")
    result, _ = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert installed_image(fake).read_bytes() == (fake.remote / ASSET).read_bytes()
    assert "removed unverified quarantine" in result.stdout
    assert quarantines(fake) == []
    assert rollbacks(fake) == []
    assert_private_cleanup(fake)


@pytest.mark.parametrize("consent", ["no", "nonTTY"])
def test_unverified_consent_denied_has_no_quarantine_or_mutation(
    tmp_path: Path, consent: str
) -> None:
    fake, script = app_harness(tmp_path)
    _, altered = seed_altered_previous(fake, active=True)
    inode = installed_image(fake).stat().st_ino
    master = slave = None
    try:
        if consent == "no":
            master, slave = pty.openpty()
            os.write(master, b"n\n")
        result, commands = fake.run("--version", TAG, script=script, input_fd=slave)
    finally:
        if master is not None and slave is not None:
            os.close(master)
            os.close(slave)
    assert result.returncode != 0
    assert "canceled" in result.stderr
    assert mutations(commands) == []
    assert installed_image(fake).read_bytes() == altered
    assert installed_image(fake).stat().st_ino == inode
    assert stamp(fake).read_text() == PREVIOUS_TAG + "\n"
    assert quarantines(fake) == []
    assert_private_cleanup(fake)


@pytest.mark.parametrize("failure", ["stop", "active"])
def test_unverified_stop_failure_never_replaces_or_quarantines(
    tmp_path: Path, failure: str
) -> None:
    fake, script = app_harness(tmp_path)
    _, altered = seed_altered_previous(fake, active=True)
    if failure == "stop":
        fake.configure(unit_failure="stop")
    else:
        fake.configure(stop_state=failure)
    inode = installed_image(fake).stat().st_ino
    result, commands = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode != 0
    assert "stop" in result.stderr
    assert installed_image(fake).read_bytes() == altered
    assert installed_image(fake).stat().st_ino == inode
    assert stamp(fake).read_text() == PREVIOUS_TAG + "\n"
    assert not any(c[0] in {"sudo", ASSET} for c in commands)
    assert quarantines(fake) == []
    assert_private_cleanup(fake)


@pytest.mark.parametrize("failure", ["integration", "helper", "daemon-reload", "enable"])
def test_unverified_after_stop_failure_stays_stopped_with_quarantine(
    tmp_path: Path, failure: str
) -> None:
    fake, script = app_harness(tmp_path, helper=HELPER_OK)
    _, altered = seed_altered_previous(fake, active=True)
    profile = fake.root / "home/.config/naga-control/profiles.toml"
    profile.parent.mkdir(parents=True)
    profile.write_text("user profile untouched\n")
    if failure == "integration":
        fake.configure(integration_failure=1)
    elif failure == "helper":
        fake.configure(helper_install_failure=42)
    else:
        fake.configure(unit_failure=failure, unit_failure_once=True)
    args = ["--version", TAG, "--restart-service"]
    if failure == "helper":
        args.append("--install-openrazer")
    result, commands = fake.run(*args, script=script)
    assert result.returncode != 0
    assert "failed" in result.stderr or "remains stopped" in result.stderr + result.stdout
    assert "unverified" in result.stderr + result.stdout
    assert "manual recovery" in result.stderr + result.stdout
    assert "app installed;" not in result.stdout
    assert "installation staged:" not in result.stdout
    assert "rollback restored" not in result.stdout + result.stderr
    assert profile.read_text() == "user profile untouched\n"
    assert not any(c[0] == "systemctl" and c[2] == "start" for c in commands)
    if failure == "enable":
        # The failed activation itself is an enable --now attempt; it must
        # not have started the service.
        assert ["systemctl", "--user", "enable", "--now", "naga-control.service"] in commands
    else:
        assert not any("--now" in c for c in commands)
    state = json.loads((fake.root / "state.json").read_text())
    assert state["service_state"] == "inactive"
    assert state["unit_state"] == "disabled"
    if failure in {"integration", "helper"}:
        # Before TOUCHED the verified replacement never landed.
        assert installed_image(fake).read_bytes() == altered
        assert stamp(fake).read_text() == PREVIOUS_TAG + "\n"
    else:
        # After TOUCHED the verified image/stamp are retained; no
        # automatic restore of the unverified bytes is permitted.
        assert installed_image(fake).read_bytes() == (fake.remote / ASSET).read_bytes()
        assert stamp(fake).read_text() == TAG + "\n"
    _quarantine_ok(fake, altered, PREVIOUS_TAG)
    assert_private_cleanup(fake)


def test_unverified_touched_failure_leaves_stopped_disabled_and_quarantined(
    tmp_path: Path,
) -> None:
    fake, script = app_harness(tmp_path)
    _, altered = seed_altered_previous(fake, active=True)
    fake.configure(unit_failure="daemon-reload")
    result, commands = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode != 0
    assert "unverified" in result.stderr + result.stdout
    assert "manual recovery" in result.stderr + result.stdout
    assert "app installed;" not in result.stdout
    state = json.loads((fake.root / "state.json").read_text())
    assert state["service_state"] == "inactive"
    assert state["unit_state"] == "disabled"
    assert not any(c[0] == "systemctl" and c[2] == "start" for c in commands)
    kept = _quarantine_ok(fake, altered, PREVIOUS_TAG)
    assert kept.exists()
    assert_private_cleanup(fake)


def test_inactive_unverified_failure_never_activates(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    _, altered = seed_altered_previous(fake, active=False)
    fake.configure(integration_failure=1)
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode != 0
    assert installed_image(fake).read_bytes() == altered
    assert stamp(fake).read_text() == PREVIOUS_TAG + "\n"
    assert not any(c[0] == "systemctl" and c[2] in {"start", "enable"} for c in commands)
    state = json.loads((fake.root / "state.json").read_text())
    assert state["service_state"] == "inactive"
    assert state["unit_state"] == "disabled"
    assert "unverified" in result.stderr + result.stdout
    _quarantine_ok(fake, altered, PREVIOUS_TAG)
    assert_private_cleanup(fake)


def test_verified_upgrade_still_uses_rollback_not_quarantine(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    previous = seed_previous(fake, active=True)
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    assert "keeping newest verified rollback" in result.stdout
    assert quarantines(fake) == []
    kept = rollbacks(fake)
    assert len(kept) == 1
    assert (kept[0] / "naga-control.AppImage").read_bytes() == previous
    assert (kept[0] / "image.sha256").is_file()
    assert (kept[0] / "installer-backup").read_text() == "naga-control-installer-backup-v1\n"
    assert_private_cleanup(fake)


def test_uninstall_leaves_quarantine_for_manual_cleanup(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    _, altered = seed_altered_previous(fake, active=False)
    fake.configure(integration_failure=1)
    result, _ = fake.run("--version", TAG, script=script)
    assert result.returncode != 0
    assert "unverified" in result.stdout + result.stderr
    kept = quarantines(fake)[0]
    assert (kept / "naga-control.AppImage").read_bytes() == altered
    uninstall = fake.root / "uninstall.sh"
    uninstall.write_text(
        (ROOT / "scripts/uninstall.sh")
        .read_text()
        .replace("/etc/udev/rules.d", str(fake.root / "missing-udev-rules"))
    )
    result, _ = fake.run("--yes", script=uninstall)
    assert result.returncode == 0, result.stderr
    assert kept.is_dir()
    assert (kept / "naga-control.AppImage").read_bytes() == altered
    assert not stamp(fake).exists()
