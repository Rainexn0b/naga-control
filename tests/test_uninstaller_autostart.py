"""Naga-owned autostart cleanup only; foreign entries never touched."""

import os
from pathlib import Path

import pytest

from tests.uninstaller_fakes import PROFILES, UninstallerHarness, harness

NAME = "org.nagacontrol.NagaControl.desktop"


def owned_text(exec_line: str = "/tmp/fake-launcher --start-hidden", hidden: str = "false") -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Naga Control\n"
        "Icon=org.nagacontrol.NagaControl\n"
        f"Exec={exec_line}\n"
        f"Hidden={hidden}\n"
        "X-NagaControl-Owned=true\n"
    )


def expected_path(fake: UninstallerHarness, xdg: str | None) -> Path:
    if xdg is not None and xdg.startswith("/"):
        return Path(xdg) / "autostart" / NAME
    return fake.home / ".config" / "autostart" / NAME


def write_entry(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_owned_removed_normal_and_purge_preserve_policy(tmp_path: Path) -> None:
    for purge in (False, True):
        fake = harness(tmp_path / f"normal-{purge}")
        fake.seed()
        target = expected_path(fake, None)
        write_entry(target, owned_text())
        other = target.parent / "other-app.desktop"
        write_entry(other, "[Desktop Entry]\nType=Application\nExec=/usr/bin/other\n")
        args = ("--yes", "--purge-config") if purge else ("--yes",)
        result, _ = fake.run(*args, reply="n\n")
        assert result.returncode == 0, result.stderr
        assert "uninstall complete" in result.stdout
        assert "removed owned autostart" in result.stdout
        assert not target.exists()
        assert other.read_text() == "[Desktop Entry]\nType=Application\nExec=/usr/bin/other\n"
        assert target.parent.is_dir()
        if purge:
            assert not (fake.home / ".config/naga-control").exists()
        else:
            assert (fake.home / PROFILES).is_file()


def test_absolute_xdg_inside_and_outside_home(tmp_path: Path) -> None:
    fake = harness(tmp_path / "inside")
    fake.seed()
    inside = str(fake.home / "custom-config")
    fake.environment["XDG_CONFIG_HOME"] = inside
    target = expected_path(fake, inside)
    write_entry(target, owned_text())
    result, _ = fake.run("--yes", reply="n\n")
    assert result.returncode == 0, result.stderr
    assert not target.exists()

    fake2 = harness(tmp_path / "outside")
    fake2.seed()
    outside = str(fake2.root / "custom-config")
    fake2.environment["XDG_CONFIG_HOME"] = outside
    target2 = expected_path(fake2, outside)
    write_entry(target2, owned_text())
    result2, _ = fake2.run("--yes", reply="n\n")
    assert result2.returncode == 0, result2.stderr
    assert not target2.exists()
    # Home fallback must not be touched when XDG is outside.
    assert not (fake2.home / ".config/autostart" / NAME).exists()


def test_relative_xdg_falls_back_to_home(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    fake.seed()
    fake.environment["XDG_CONFIG_HOME"] = "relative/path"
    target = expected_path(fake, None)
    write_entry(target, owned_text())
    result, _ = fake.run("--yes", reply="n\n")
    assert result.returncode == 0, result.stderr
    assert not target.exists()


def test_moved_exec_and_hidden_true_still_owned(tmp_path: Path) -> None:
    fake = harness(tmp_path / "moved")
    fake.seed()
    write_entry(expected_path(fake, None), owned_text("/old/moved --start-hidden"))
    result, _ = fake.run("--yes", reply="n\n")
    assert result.returncode == 0, result.stderr
    assert not expected_path(fake, None).exists()

    fake2 = harness(tmp_path / "hidden")
    fake2.seed()
    write_entry(expected_path(fake2, None), owned_text(hidden="true"))
    result2, _ = fake2.run("--yes", reply="n\n")
    assert result2.returncode == 0, result2.stderr
    assert not expected_path(fake2, None).exists()


@pytest.mark.parametrize(
    "kind",
    ["foreign", "missing-marker", "other-section", "symlink", "broken-symlink", "directory"],
)
def test_foreign_kinds_preserved_with_success(tmp_path: Path, kind: str) -> None:
    fake = harness(tmp_path)
    fake.seed()
    target = expected_path(fake, None)
    target.parent.mkdir(parents=True, exist_ok=True)
    other = target.parent / "other-app.desktop"
    other.write_text("[Desktop Entry]\nType=Application\nExec=/usr/bin/other\n")
    if kind == "foreign":
        target.write_text("[Desktop Entry]\nType=Application\nExec=/usr/bin/other\n")
    elif kind == "missing-marker":
        target.write_text("[Desktop Entry]\nType=Application\nExec=/tmp/x --start-hidden\n")
    elif kind == "other-section":
        target.write_text(
            "[Desktop Other]\nX-NagaControl-Owned=true\n"
            "[Desktop Entry]\nType=Application\nExec=/tmp/x --start-hidden\n"
        )
    elif kind == "symlink":
        real = fake.root / "real.desktop"
        real.write_text(owned_text())
        target.symlink_to(real)
    elif kind == "broken-symlink":
        target.symlink_to(fake.root / "missing-target.desktop")
    else:
        target.mkdir()
    result, _ = fake.run("--yes", reply="n\n")
    assert result.returncode == 0, result.stderr
    assert "uninstall complete" in result.stdout
    assert other.read_text() == "[Desktop Entry]\nType=Application\nExec=/usr/bin/other\n"
    if kind in {"symlink", "broken-symlink"}:
        assert target.is_symlink()
    elif kind == "directory":
        assert target.is_dir()
    else:
        assert target.is_file()
    # App files are still removed on foreign preserve.
    assert not (fake.home / ".local/bin/naga-control.AppImage").exists()


def test_missing_entry_is_nothing(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    fake.seed()
    assert not expected_path(fake, None).exists()
    result, _ = fake.run("--yes", reply="n\n")
    assert result.returncode == 0, result.stderr
    assert "uninstall complete" in result.stdout


def test_unsafe_parent_mode_blocks_deletion(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    contents = fake.seed()
    target = expected_path(fake, None)
    write_entry(target, owned_text())
    target.parent.chmod(0o777)
    try:
        result, commands = fake.run("--yes", reply="n\n")
    finally:
        target.parent.chmod(0o755)
    assert result.returncode != 0
    assert "uninstall complete" not in result.stdout
    assert target.is_file()
    assert not any(cmd[0] in {"rm", "rmdir", "sudo"} for cmd in commands)
    assert not any(cmd[0] == "systemctl" for cmd in commands)
    for rel, content in contents.items():
        assert (fake.home / rel).read_bytes() == content


def test_unsafe_ancestor_symlink_blocks_before_service(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    contents = fake.seed()
    target = expected_path(fake, None)
    write_entry(target, owned_text())
    ancestor = fake.home / ".config"
    outside = fake.root / "outside-config"
    ancestor.rename(outside)
    ancestor.symlink_to(outside, target_is_directory=True)
    try:
        result, commands = fake.run("--yes", reply="n\n")
    finally:
        ancestor.unlink()
        outside.rename(ancestor)
    assert result.returncode != 0
    assert "symlink" in result.stderr
    assert "uninstall complete" not in result.stdout
    assert not any(cmd[0] == "systemctl" for cmd in commands)
    assert not any(cmd[0] in {"rm", "rmdir", "sudo"} for cmd in commands)
    for rel, content in contents.items():
        assert (fake.home / rel).read_bytes() == content


def test_unreadable_entry_reports_error_without_deletion(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    contents = fake.seed()
    target = expected_path(fake, None)
    write_entry(target, owned_text())
    target.chmod(0o000)
    try:
        result, commands = fake.run("--yes", reply="n\n")
    finally:
        target.chmod(0o644)
    assert result.returncode != 0
    assert "uninstall complete" not in result.stdout
    assert target.is_file()
    assert not any(cmd[0] in {"rm", "rmdir", "sudo"} for cmd in commands)
    assert not any(cmd[0] == "systemctl" for cmd in commands)
    for rel, content in contents.items():
        assert (fake.home / rel).read_bytes() == content


def test_stop_failure_preserves_autostart_and_app(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    contents = fake.seed()
    target = expected_path(fake, None)
    write_entry(target, owned_text())
    contents[str(target.relative_to(fake.home))] = target.read_bytes()
    fake.configure(unit_failure="stop")
    result, commands = fake.run("--yes")
    assert result.returncode != 0
    assert "manual recovery required" in result.stderr
    assert "uninstall complete" not in result.stdout
    assert target.is_file()
    for rel, content in contents.items():
        assert (fake.home / rel).read_bytes() == content
    assert not any(cmd[0] in {"rm", "rmdir", "sudo"} for cmd in commands)


def test_remove_failure_reports_incomplete(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    fake.seed()
    target = expected_path(fake, None)
    write_entry(target, owned_text())
    fake.configure(rm_failure=str(target))
    result, _ = fake.run("--yes", reply="n\n")
    assert result.returncode != 0
    assert "uninstall incomplete" in result.stderr
    assert "uninstall complete" not in result.stdout
    assert target.is_file()
    assert fake.lock.is_file()


def test_invalid_absolute_xdg_rejected_before_cleanup(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    contents = fake.seed()
    fake.environment["XDG_CONFIG_HOME"] = "/tmp/../evil"
    result, commands = fake.run("--yes", reply="n\n")
    assert result.returncode != 0
    assert "XDG_CONFIG_HOME" in result.stderr
    assert "uninstall complete" not in result.stdout
    assert not any(cmd[0] == "systemctl" for cmd in commands)
    assert not any(cmd[0] in {"rm", "rmdir", "sudo"} for cmd in commands)
    for rel, content in contents.items():
        assert (fake.home / rel).read_bytes() == content


def test_empty_xdg_falls_back_and_missing_type_preserved(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    fake.seed()
    fake.environment["XDG_CONFIG_HOME"] = ""
    target = expected_path(fake, None)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("[Desktop Entry]\nX-NagaControl-Owned=true\nExec=/tmp/x\n")
    result, _ = fake.run("--yes", reply="n\n")
    assert result.returncode == 0, result.stderr
    assert target.is_file()
    assert "foreign" in result.stdout.lower() or "retained" in result.stdout.lower()
    assert os.path.isfile(target)
