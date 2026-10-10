"""Retention safety: untrusted snapshots are left byte-identical, never followed."""

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


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}


def _run_unchanged(fake: InstallerHarness, script: Path):
    return fake.run("--version", TAG, "--restart-service", script=script)


@pytest.mark.parametrize(
    "corrupt",
    [
        "missing-marker",
        "wrong-marker",
        "marker-nul",
        "marker-extra-row",
        "tag-extra-row",
        "tag-nul",
        "digest-uppercase",
        "digest-extra-row",
        "image-mismatch",
        "image-empty",
        "extra-note",
        "hidden-note",
        "subdir",
        "file-symlink",
    ],
)
def test_untrusted_rollback_left_byte_identical(tmp_path: Path, corrupt: str) -> None:
    fake, script = app_harness(tmp_path)
    seed_previous(fake)
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    target = rollbacks(fake)[0]
    before = _snapshot(target)
    outside = fake.root / "outside"
    outside.write_text("retain outside\n")
    if corrupt == "missing-marker":
        (target / "installer-backup").unlink()
    elif corrupt == "wrong-marker":
        (target / "installer-backup").write_text("not installer-owned\n")
    elif corrupt == "marker-nul":
        (target / "installer-backup").write_bytes(b"naga-control-installer-backup-v1\0\n")
    elif corrupt == "marker-extra-row":
        (target / "installer-backup").write_text("naga-control-installer-backup-v1\nsecond\n")
    elif corrupt == "tag-extra-row":
        (target / "installed-tag").write_text("v0.3.0\nsecond\n")
    elif corrupt == "tag-nul":
        (target / "installed-tag").write_bytes(b"v0.3.0\0\n")
    elif corrupt == "digest-uppercase":
        row = (target / "image.sha256").read_text()
        (target / "image.sha256").write_text(row[:64].upper() + row[64:])
    elif corrupt == "digest-extra-row":
        (target / "image.sha256").write_text((target / "image.sha256").read_text() + "extra\n")
    elif corrupt == "image-mismatch":
        (target / "naga-control.AppImage").write_bytes(b"tampered image\n")
    elif corrupt == "image-empty":
        (target / "naga-control.AppImage").write_bytes(b"")
    elif corrupt == "extra-note":
        (target / "operator-notes").write_text("retain\n")
        before = _snapshot(target)
    elif corrupt == "hidden-note":
        (target / ".hidden-notes").write_text("retain hidden\n")
        before = _snapshot(target)
    elif corrupt == "subdir":
        (target / "notes").mkdir()
        (target / "notes" / "link").symlink_to(outside)
    elif corrupt == "file-symlink":
        (target / "naga-control.AppImage").unlink()
        (target / "naga-control.AppImage").symlink_to(outside)
    if corrupt in ("wrong-marker", "marker-nul", "marker-extra-row", "tag-extra-row"):
        before = _snapshot(target)
    if corrupt in ("tag-nul", "digest-uppercase", "digest-extra-row", "image-mismatch"):
        before = _snapshot(target)
    if corrupt == "image-empty":
        before = _snapshot(target)
    result, commands = _run_unchanged(fake, script)
    assert result.returncode == 0, result.stderr
    assert target.is_dir() and not target.is_symlink()
    if corrupt not in {"missing-marker", "file-symlink", "subdir"}:
        assert _snapshot(target) == before
    if corrupt == "subdir":
        assert (target / "notes" / "link").is_symlink()
    assert outside.read_text() == "retain outside\n"
    assert len([c for c in commands if c[0] == ASSET]) == 2
    assert_private_cleanup(fake)


@pytest.mark.parametrize("dirname", ["rollback.too-long", "rollback.abc", "rollback.ab!12"])
def test_wrong_rollback_pattern_ignored(tmp_path: Path, dirname: str) -> None:
    fake, script = app_harness(tmp_path)
    seed_previous(fake)
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    state = stamp(fake).parent
    valid_before = rollbacks(fake)[0]
    target = state / dirname
    target.mkdir(mode=0o700)
    (target / "naga-control.AppImage").write_text("not owned content\n")
    before = _snapshot(target)
    result, _ = _run_unchanged(fake, script)
    assert result.returncode == 0, result.stderr
    assert _snapshot(target) == before
    assert valid_before.is_dir()
    assert target.is_dir()
    assert_private_cleanup(fake)


def test_rollback_dir_symlink_never_followed(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    seed_previous(fake)
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    valid = rollbacks(fake)[0]
    valid_bytes = _snapshot(valid)
    link = stamp(fake).parent / "rollback.aaaaaa"
    link.symlink_to(valid, target_is_directory=True)
    outside = fake.root / "outside-target"
    outside.write_text("outside\n")
    result, _ = _run_unchanged(fake, script)
    assert result.returncode == 0, result.stderr
    assert link.is_symlink()
    assert _snapshot(valid) == valid_bytes
    assert outside.read_text() == "outside\n"
    assert_private_cleanup(fake)


def test_world_writable_rollback_left(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    seed_previous(fake)
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    target = rollbacks(fake)[0]
    before = _snapshot(target)
    target.chmod(0o777)
    try:
        result, _ = _run_unchanged(fake, script)
    finally:
        target.chmod(0o700)
    assert result.returncode == 0, result.stderr
    assert _snapshot(target) == before
    assert_private_cleanup(fake)


def test_foreign_rollback_left(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    seed_previous(fake)
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    target = rollbacks(fake)[0]
    before = _snapshot(target)
    # Dynamic foreign UID: fixture files are owned by the harness UID, so
    # owner+1 stays foreign on any host (including a host UID of 1234).
    owner_uid = target.stat().st_uid
    fake.configure(uid=str(owner_uid + 1))
    result, _ = _run_unchanged(fake, script)
    assert result.returncode == 0, result.stderr
    assert _snapshot(target) == before
    assert_private_cleanup(fake)


@pytest.mark.parametrize(
    "corrupt",
    ["marker-short", "marker-nul", "tag-mismatch", "extra-note", "file-symlink"],
)
def test_untrusted_quarantine_left(tmp_path: Path, corrupt: str) -> None:
    fake, script = app_harness(tmp_path)
    _, altered = seed_altered_previous(fake, active=False)
    fake.configure(integration_failure=1)
    result, _ = fake.run("--version", TAG, script=script)
    assert result.returncode != 0
    target = quarantines(fake)[0]
    assert (target / "naga-control.AppImage").read_bytes() == altered
    outside = fake.root / "outside-q"
    outside.write_text("retain q\n")
    if corrupt == "marker-short":
        (target / "quarantine").write_text("naga-control-installer-quarantine-v1\n")
    elif corrupt == "marker-nul":
        (target / "quarantine").write_bytes(
            (target / "quarantine").read_bytes().rstrip(b"\n") + b"\0\n"
        )
    elif corrupt == "tag-mismatch":
        (target / "installed-tag").write_text("v9.9.9\n")
    elif corrupt == "extra-note":
        (target / "operator-notes").write_text("retain\n")
    elif corrupt == "file-symlink":
        (target / "naga-control.AppImage").unlink()
        (target / "naga-control.AppImage").symlink_to(outside)
    before_names = sorted(p.name for p in target.iterdir())
    fake.configure(integration_failure=0)
    live = installed_image(fake)
    live.write_bytes(live.read_bytes() + b"\n# second dirty\n")
    result, _ = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert target.is_dir() and not target.is_symlink()
    assert sorted(p.name for p in target.iterdir()) == before_names
    assert outside.read_text() == "retain q\n"
    assert_private_cleanup(fake)


def test_quarantine_dir_symlink_never_followed(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    _, altered = seed_altered_previous(fake, active=False)
    fake.configure(integration_failure=1)
    result, _ = fake.run("--version", TAG, script=script)
    assert result.returncode != 0
    valid = quarantines(fake)[0]
    assert (valid / "naga-control.AppImage").read_bytes() == altered
    link = stamp(fake).parent / "quarantine.bbbbbb"
    link.symlink_to(valid, target_is_directory=True)
    fake.configure(integration_failure=0)
    installed_image(fake).write_bytes(altered + b"\n# again\n")
    result, _ = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert link.is_symlink()
    assert not valid.exists()
    assert quarantines(fake) == [link]
    assert_private_cleanup(fake)


def test_valid_rollback_hash_never_executes_old_image(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    seed_previous(fake)
    result, commands = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    executions = [c for c in commands if c[0] == ASSET]
    assert len(executions) == 1
    assert executions[0][1] == "--install"
    assert_private_cleanup(fake)
    expected = 1
    for _ in range(2):
        result, commands = _run_unchanged(fake, script)
        assert result.returncode == 0, result.stderr
        expected += 1
        assert len([c for c in commands if c[0] == ASSET]) == expected
        assert len(rollbacks(fake)) == 1
    assert_private_cleanup(fake)


def test_ancestor_symlink_above_home_retained(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    seed_previous(fake)
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    first = rollbacks(fake)[0]
    payload = (first / "naga-control.AppImage").read_bytes()
    tag = (first / "installed-tag").read_text()
    digest = (first / "image.sha256").read_text()
    marker = (first / "installer-backup").read_text()
    second = stamp(fake).parent / "rollback.bbbbbb"
    second.mkdir(mode=0o700)
    (second / "naga-control.AppImage").write_bytes(payload)
    (second / "installed-tag").write_text(tag)
    (second / "image.sha256").write_text(digest)
    (second / "installer-backup").write_text(marker)
    second.chmod(0o700)
    before = {p.name: _snapshot(p) for p in rollbacks(fake)}
    assert len(before) == 2
    link = tmp_path / "link-fakes"
    link.symlink_to(fake.root, target_is_directory=True)
    assert str(link).startswith(str(tmp_path))
    fake.environment["HOME"] = str(link / "home")
    result, _ = _run_unchanged(fake, script)
    assert result.returncode == 0, result.stderr
    assert "retention left untrusted" in result.stdout
    kept = rollbacks(fake)
    assert len(kept) == 2
    for kept_dir in kept:
        assert _snapshot(kept_dir) == before[kept_dir.name]
    assert_private_cleanup(fake)


def test_world_writable_ancestor_within_home_retained(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    seed_previous(fake)
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    first = rollbacks(fake)[0]
    payload = (first / "naga-control.AppImage").read_bytes()
    tag = (first / "installed-tag").read_text()
    digest = (first / "image.sha256").read_text()
    marker = (first / "installer-backup").read_text()
    second = stamp(fake).parent / "rollback.cccccc"
    second.mkdir(mode=0o700)
    (second / "naga-control.AppImage").write_bytes(payload)
    (second / "installed-tag").write_text(tag)
    (second / "image.sha256").write_text(digest)
    (second / "installer-backup").write_text(marker)
    second.chmod(0o700)
    before = {p.name: _snapshot(p) for p in rollbacks(fake)}
    assert len(before) == 2
    dotlocal = fake.root / "home" / ".local"
    old_mode = dotlocal.stat().st_mode & 0o777
    dotlocal.chmod(0o777)
    try:
        result, _ = _run_unchanged(fake, script)
    finally:
        dotlocal.chmod(old_mode)
    assert result.returncode == 0, result.stderr
    assert "retention left untrusted" in result.stdout
    kept = rollbacks(fake)
    assert len(kept) == 2
    for kept_dir in kept:
        assert _snapshot(kept_dir) == before[kept_dir.name]
    assert_private_cleanup(fake)
