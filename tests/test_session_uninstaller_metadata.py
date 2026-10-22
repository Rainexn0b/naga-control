"""Mode metadata: NUL, ancestors, both-mode marker, unit conflict."""

from pathlib import Path

from tests.session_uninstaller_fakes import (
    ACTIVATION,
    HELPER,
    IMAGE,
    MODE,
    session_harness,
)


def test_mode_nul_bytes_rejected_before_mutations(tmp_path: Path) -> None:
    for name, payload in (
        ("session-nul", b"session\x00"),
        ("systemd-nul", b"systemd\x00"),
        ("session-nul-nl", b"session\n\x00"),
    ):
        fake = session_harness(tmp_path / name)
        contents = fake.seed_session()
        (fake.home / MODE).write_bytes(payload)
        result, commands = fake.run("--yes")
        assert result.returncode != 0, name
        assert "uninstall complete" not in result.stdout
        assert fake.dbus_calls() == []
        assert not any(cmd[0] in {"rm", "rmdir", "sudo", "mv"} for cmd in commands)
        for relative in (IMAGE, HELPER, ACTIVATION):
            assert (fake.home / relative).read_bytes() == contents[relative]


def test_mode_symlink_ancestor_fails_closed_not_legacy(tmp_path: Path) -> None:
    fake = session_harness(tmp_path)
    contents = fake.seed_session()
    ancestor = fake.home / ".local"
    outside = fake.root / "outside-local"
    outside.mkdir()
    # Move real .local aside, link it, then restore after the run.
    real = fake.root / "real-local"
    ancestor.rename(real)
    ancestor.symlink_to(outside, target_is_directory=True)
    try:
        result, commands = fake.run("--yes")
    finally:
        ancestor.unlink()
        real.rename(ancestor)
    assert result.returncode != 0
    assert "uninstall complete" not in result.stdout
    assert "service manager is misconfigured" in result.stderr
    assert "systemctl is required" not in result.stderr
    assert fake.dbus_calls() == []
    assert not any(cmd[0] in {"rm", "rmdir", "sudo", "mv"} for cmd in commands)
    for relative in (IMAGE, HELPER, ACTIVATION):
        assert (fake.home / relative).read_bytes() == contents[relative]


def test_systemd_marker_removed_after_safe_stop_no_extra_tools(tmp_path: Path) -> None:
    from tests.uninstaller_fakes import harness as legacy_harness

    fake = legacy_harness(tmp_path)
    fake.seed()
    mode = fake.home / ".local/share/naga-control/service-manager"
    mode.parent.mkdir(parents=True, exist_ok=True)
    mode.write_text("systemd\n")
    mode.chmod(0o600)
    result, commands = fake.run("--yes")
    assert result.returncode == 0, result.stderr
    assert "uninstall complete" in result.stdout
    assert not mode.exists()
    assert not any(cmd[0] in {"dbus-send", "mktemp", "python", "python3"} for cmd in commands)


def test_legacy_absent_mode_still_uninstalls(tmp_path: Path) -> None:
    from tests.uninstaller_fakes import harness as legacy_harness

    fake = legacy_harness(tmp_path)
    fake.seed()
    assert not (fake.home / ".local/share/naga-control/service-manager").exists()
    result, _ = fake.run("--yes")
    assert result.returncode == 0, result.stderr
    assert "uninstall complete" in result.stdout


def test_session_with_existing_unit_fails_for_manual_migration(tmp_path: Path) -> None:
    fake = session_harness(tmp_path)
    contents = fake.seed_session()
    unit = fake.home / ".config/systemd/user/naga-control.service"
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text("[Unit]\nDescription=naga\n")
    result, commands = fake.run("--yes")
    assert result.returncode != 0
    assert "unexpected systemd unit" in result.stderr
    assert "manual" in result.stderr.lower()
    assert "uninstall complete" not in result.stdout
    assert fake.dbus_calls() == []
    assert not any(cmd[0] in {"rm", "rmdir", "sudo", "mv"} for cmd in commands)
    for relative, data in contents.items():
        assert (fake.home / relative).read_bytes() == data
    assert unit.read_text() == "[Unit]\nDescription=naga\n"


def test_unexpected_unit_blocks_even_when_inactive(tmp_path: Path) -> None:
    fake = session_harness(tmp_path, {"has_owner": False})
    fake.seed_session(has_owner=False)
    unit = fake.home / ".config/systemd/user/naga-control.service"
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text("[Unit]\n")
    result, _ = fake.run("--yes")
    assert result.returncode != 0
    assert fake.dbus_calls() == []
    assert unit.is_file()
    assert (fake.home / IMAGE).is_file()
