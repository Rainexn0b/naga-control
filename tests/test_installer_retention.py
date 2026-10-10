"""One-rollback retention after committed success; failures preserve recovery."""

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from tests.installer_app_fakes import (
    ASSET,
    app_harness,
    assert_private_cleanup,
    installed_image,
    quarantines,
    rollbacks,
    seed_altered_previous,
    seed_previous,
    stamp,
)
from tests.openrazer_installer_fakes import TAG, InstallerHarness


def _remote_bytes(fake: InstallerHarness) -> bytes:
    return (fake.remote / ASSET).read_bytes()


def test_successive_verified_upgrades_keep_only_newest(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    seed_previous(fake)
    profile = fake.root / "home/.config/naga-control/profiles.toml"
    profile.parent.mkdir(parents=True)
    profile.write_text("user profile\n")
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    assert len(rollbacks(fake)) == 1
    old_v04 = _remote_bytes(fake)
    fake.remote.joinpath(ASSET).write_bytes(old_v04 + b"\n# v0.5.0 fixture\n")
    fake.remote.joinpath(ASSET + ".sha256").write_text(
        hashlib.sha256(fake.remote.joinpath(ASSET).read_bytes()).hexdigest() + "  " + ASSET + "\n"
    )
    fake.configure(previous_tag=TAG, previous_digest=hashlib.sha256(old_v04).hexdigest())
    result, _ = fake.run("--version", "v0.5.0", "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    assert "keeping newest verified rollback" in result.stdout
    assert "removed older verified rollback" in result.stdout
    kept = rollbacks(fake)
    assert len(kept) == 1
    assert (kept[0] / "naga-control.AppImage").read_bytes() == old_v04
    assert (kept[0] / "installed-tag").read_text() == TAG + "\n"
    assert quarantines(fake) == []
    assert installed_image(fake).read_bytes() == _remote_bytes(fake)
    assert stamp(fake).read_text() == "v0.5.0\n"
    assert profile.read_text() == "user profile\n"
    assert_private_cleanup(fake)


def test_mtime_tie_keeps_lexicographically_largest(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    seed_previous(fake)
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    first = rollbacks(fake)[0]
    payload = (first / "naga-control.AppImage").read_bytes()
    tag = (first / "installed-tag").read_text()
    digest = (first / "image.sha256").read_text()
    marker = (first / "installer-backup").read_text()
    shutil.rmtree(first)
    state = stamp(fake).parent
    for suffix in ("aaaaaa", "zzzzzz"):
        target = state / f"rollback.{suffix}"
        target.mkdir(mode=0o700)
        (target / "naga-control.AppImage").write_bytes(payload)
        (target / "installed-tag").write_text(tag)
        (target / "image.sha256").write_text(digest)
        (target / "installer-backup").write_text(marker)
        target.chmod(0o700)
    fixed = 1234567890
    os.utime(state / "rollback.aaaaaa", (fixed, fixed))
    os.utime(state / "rollback.zzzzzz", (fixed, fixed))
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    kept = rollbacks(fake)
    assert len(kept) == 1
    assert kept[0].name == "rollback.zzzzzz"
    assert "keeping newest verified rollback" in result.stdout
    assert_private_cleanup(fake)


def test_unverified_success_clears_current_and_historic_quarantines(
    tmp_path: Path,
) -> None:
    fake, script = app_harness(tmp_path)
    seed_previous(fake)
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    first_backup = rollbacks(fake)[0]
    first_bytes = (first_backup / "naga-control.AppImage").read_bytes()
    live = installed_image(fake)
    live.write_bytes(live.read_bytes() + b"\n# locally rebuilt\n")
    fake.configure(integration_failure=1)
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode != 0
    assert len(quarantines(fake)) == 1
    fake.configure(integration_failure=0)
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    assert "removed unverified quarantine" in result.stdout
    assert quarantines(fake) == []
    kept = rollbacks(fake)
    assert len(kept) == 1
    assert kept[0] == first_backup
    assert (kept[0] / "naga-control.AppImage").read_bytes() == first_bytes
    assert_private_cleanup(fake)


def test_repeated_success_is_idempotent(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    seed_previous(fake)
    profile = fake.root / "home/.config/naga-control/profiles.toml"
    profile.parent.mkdir(parents=True)
    profile.write_text("stable\n")
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    image_bytes = installed_image(fake).read_bytes()
    tag = stamp(fake).read_text()
    backups = rollbacks(fake)
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    assert installed_image(fake).read_bytes() == image_bytes
    assert stamp(fake).read_text() == tag
    assert profile.read_text() == "stable\n"
    assert rollbacks(fake) == backups
    assert quarantines(fake) == []
    assert_private_cleanup(fake)


@pytest.mark.parametrize("failure", ["integration", "cancel", "new-checksum"])
def test_failure_preserves_prior_snapshots(tmp_path: Path, failure: str) -> None:
    fake, script = app_harness(tmp_path)
    seed_previous(fake)
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    backup = rollbacks(fake)[0]
    backup_files = {p.name: p.read_bytes() for p in backup.iterdir()}
    live = installed_image(fake)
    live.write_bytes(live.read_bytes() + b"\n# dirty\n")
    fake.configure(integration_failure=1)
    failed, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert failed.returncode != 0
    historic = quarantines(fake)[0]
    historic_files = {p.name: p.read_bytes() for p in historic.iterdir()}
    fake.configure(integration_failure=0)
    if failure == "integration":
        fake.configure(integration_failure=1)
        result, _ = fake.run("--version", TAG, "--restart-service", script=script)
        assert result.returncode != 0
    elif failure == "cancel":
        fake.configure(service_state="active", unit_state="enabled")
        result, _ = fake.run("--version", TAG, script=script)
        assert result.returncode != 0
        assert "canceled" in result.stderr or "needs terminal" in result.stderr
    else:
        fake.remote.joinpath(ASSET).write_bytes(b"tampered-new")
        result, _ = fake.run("--version", TAG, "--restart-service", script=script)
        assert result.returncode != 0
    assert rollbacks(fake)[0].exists()
    assert {p.name: p.read_bytes() for p in backup.iterdir()} == backup_files
    assert len(quarantines(fake)) >= 1
    assert {p.name: p.read_bytes() for p in historic.iterdir()} == historic_files
    assert_private_cleanup(fake)


def test_udev_staged_success_still_cleans(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    _, altered = seed_altered_previous(fake, active=False)
    with installed_image(fake).open("rb") as held:
        fake.configure(udev_failure=1)
        result, _ = fake.run("--version", TAG, script=script)
        assert held.read() == altered
    assert result.returncode == 0, result.stderr
    assert "installation staged:" in result.stdout
    assert "removed unverified quarantine" in result.stdout
    assert quarantines(fake) == []
    assert installed_image(fake).read_bytes() == _remote_bytes(fake)
    assert_private_cleanup(fake)


def test_rm_failure_after_commit_still_succeeds(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    seed_previous(fake)
    profile = fake.root / "home/.config/naga-control/profiles.toml"
    profile.parent.mkdir(parents=True)
    profile.write_text("keep me\n")
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    assert len(rollbacks(fake)) == 1
    real_rm = shutil.which("rm")
    assert real_rm is not None
    wrapper = fake.root / "bin" / "rm"
    wrapper.unlink()
    wrapper.write_text(
        f"#!{sys.executable}\n"
        "import os\n"
        "import sys\n"
        f"real_rm = {real_rm!r}\n"
        "args = sys.argv[1:]\n"
        "if any('rollback.' in a or 'quarantine.' in a for a in args):\n"
        "    sys.stderr.write('fake rm failure\\n')\n"
        "    sys.exit(1)\n"
        "os.execv(real_rm, [real_rm, *args])\n"
    )
    wrapper.chmod(0o755)
    fake.environment["NAGA_CONTROL_FORCE_DOWNLOAD"] = "1"
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    assert "retention cleanup incomplete" in result.stdout
    assert "app installed;" in result.stdout
    assert installed_image(fake).read_bytes() == _remote_bytes(fake)
    assert profile.read_text() == "keep me\n"
    assert len(rollbacks(fake)) == 2
    assert json.loads((fake.root / "state.json").read_text())["service_state"] == "active"
    assert_private_cleanup(fake)


@pytest.mark.parametrize("fail", ["one", "all"])
def test_mtime_failure_retains_all_verified(tmp_path: Path, fail: str) -> None:
    fake, script = app_harness(tmp_path)
    seed_previous(fake)
    profile = fake.root / "home/.config/naga-control/profiles.toml"
    profile.parent.mkdir(parents=True)
    profile.write_text("stable\n")
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    first = rollbacks(fake)[0]
    payload = (first / "naga-control.AppImage").read_bytes()
    tag = (first / "installed-tag").read_text()
    digest = (first / "image.sha256").read_text()
    marker = (first / "installer-backup").read_text()
    shutil.rmtree(first)
    state = stamp(fake).parent
    for suffix in ("aaaaaa", "bbbbbb"):
        target = state / f"rollback.{suffix}"
        target.mkdir(mode=0o700)
        (target / "naga-control.AppImage").write_bytes(payload)
        (target / "installed-tag").write_text(tag)
        (target / "image.sha256").write_text(digest)
        (target / "installer-backup").write_text(marker)
        target.chmod(0o700)
    fixed = 1234567890
    os.utime(state / "rollback.aaaaaa", (fixed, fixed))
    os.utime(state / "rollback.bbbbbb", (fixed, fixed))
    before = {p.name: {q.name: q.read_bytes() for q in p.iterdir()} for p in rollbacks(fake)}
    assert len(before) == 2
    fake.configure(stat_Y_fail="all" if fail == "all" else "aaaaaa")
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    assert "could not determine newest" in result.stdout
    kept = rollbacks(fake)
    assert len(kept) == 2
    for kept_dir in kept:
        assert {q.name: q.read_bytes() for q in kept_dir.iterdir()} == before[kept_dir.name]
    assert installed_image(fake).read_bytes() == _remote_bytes(fake)
    assert stamp(fake).read_text() == TAG + "\n"
    assert profile.read_text() == "stable\n"
    assert json.loads((fake.root / "state.json").read_text())["service_state"] == "active"
    assert_private_cleanup(fake)


def test_backup_authoritative_prunes_without_mtime(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    seed_previous(fake)
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    assert len(rollbacks(fake)) == 1
    old_v04 = _remote_bytes(fake)
    fake.remote.joinpath(ASSET).write_bytes(old_v04 + b"\n# v0.5.0 fixture\n")
    fake.remote.joinpath(ASSET + ".sha256").write_text(
        hashlib.sha256(fake.remote.joinpath(ASSET).read_bytes()).hexdigest() + "  " + ASSET + "\n"
    )
    fake.configure(previous_tag=TAG, previous_digest=hashlib.sha256(old_v04).hexdigest())
    fake.configure(stat_Y_fail="all")
    result, _ = fake.run("--version", "v0.5.0", "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    assert "keeping newest verified rollback" in result.stdout
    assert "could not determine newest" not in result.stdout
    kept = rollbacks(fake)
    assert len(kept) == 1
    assert (kept[0] / "naga-control.AppImage").read_bytes() == old_v04
    assert installed_image(fake).read_bytes() == _remote_bytes(fake)
    assert stamp(fake).read_text() == "v0.5.0\n"
    assert_private_cleanup(fake)


def test_postcommit_sigterm_preserves_commit(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    seed_previous(fake)
    profile = fake.root / "home/.config/naga-control/profiles.toml"
    profile.parent.mkdir(parents=True)
    profile.write_text("keep me\n")
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    backup = rollbacks(fake)[0]
    backup_files = {p.name: p.read_bytes() for p in backup.iterdir()}
    live = installed_image(fake)
    live.write_bytes(live.read_bytes() + b"\n# dirty\n")
    fake.configure(integration_failure=1)
    failed, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert failed.returncode != 0
    assert len(quarantines(fake)) >= 1
    historic = quarantines(fake)[0]
    historic_files = {p.name: p.read_bytes() for p in historic.iterdir()}
    fake.configure(integration_failure=0)
    real_rm = shutil.which("rm")
    assert real_rm is not None
    wrapper = fake.root / "bin" / "rm"
    wrapper.unlink()
    wrapper.write_text(
        f"#!{sys.executable}\n"
        "import os\n"
        "import signal\n"
        "import sys\n"
        f"real_rm = {real_rm!r}\n"
        "args = sys.argv[1:]\n"
        "if any('rollback.' in a or 'quarantine.' in a for a in args):\n"
        "    try:\n"
        "        os.kill(os.getppid(), signal.SIGTERM)\n"
        "    except Exception:\n"
        "        pass\n"
        "    sys.exit(1)\n"
        "os.execv(real_rm, [real_rm, *args])\n"
    )
    wrapper.chmod(0o755)
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 143, result.stderr
    combined = result.stdout + result.stderr
    assert "installation already committed" in combined
    assert "installation not completed" not in combined
    assert "restoring" not in combined.lower()
    assert installed_image(fake).read_bytes() == _remote_bytes(fake)
    assert stamp(fake).read_text() == TAG + "\n"
    assert profile.read_text() == "keep me\n"
    assert json.loads((fake.root / "state.json").read_text())["service_state"] == "active"
    assert {p.name: p.read_bytes() for p in backup.iterdir()} == backup_files
    assert {p.name: p.read_bytes() for p in historic.iterdir()} == historic_files
    assert_private_cleanup(fake)
