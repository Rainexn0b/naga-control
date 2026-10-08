"""Exact app-owned cleanup independent of the installed runtime or host Python."""

import json
from pathlib import Path

import pytest

from naga_control.integration_cli import INTEGRATION_FILES
from tests.uninstaller_fakes import (
    IMAGE,
    OWNED,
    PROFILES,
    STATE,
    USER_ASSETS,
    WRAPPER,
    harness,
)


@pytest.mark.parametrize("image", ["missing", "unlaunchable", "tripwire"])
@pytest.mark.parametrize("python", [False, True])
def test_exact_cleanup_never_executes_image_wrapper_or_python(
    tmp_path: Path, image: str, python: bool
) -> None:
    fake = harness(tmp_path, python=python)
    fake.seed(image=image != "missing")
    if image == "tripwire":
        installed = fake.home / IMAGE
        installed.write_text((fake.root / "bin/id").read_text())
        installed.chmod(0o755)
    wrapper = fake.home / WRAPPER
    wrapper.write_text((fake.root / "bin/id").read_text())
    wrapper.chmod(0o755)
    unrelated = (
        ".local/bin/other-app",
        ".config/systemd/user/openrazer-daemon.service",
        ".config/openrazer/settings.conf",
        ".local/share/dbus-1/services/org.razer.service",
        ".local/share/applications/other-app.desktop",
        ".local/share/icons/hicolor/64x64/apps/other-app.png",
        f"{STATE}/operator-notes",
    )
    for relative in unrelated:
        path = fake.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("unrelated\n")
    state_before = json.loads((fake.root / "state.json").read_text())
    inode: int | None = None
    for _ in range(2):
        result, commands = fake.run("--yes")
        assert result.returncode == 0, result.stderr
        assert "uninstall complete" in result.stdout
        assert not any((fake.home / relative).exists() for relative in OWNED)
        assert (fake.home / PROFILES).read_text() == "fixture: " + PROFILES + "\n"
        for relative in unrelated:
            assert (fake.home / relative).read_text() == "unrelated\n"
        assert not any(
            command[0] in {"python", "python3", "naga-control.AppImage", "naga-control"}
            for command in commands
        )
        if inode is None:
            inode = fake.lock.stat().st_ino
        else:
            assert fake.lock.stat().st_ino == inode
        assert "OpenRazer packages, group membership, and user daemon are retained" in result.stdout
        assert not any("openrazer" in " ".join(command) for command in commands)
    state_after = json.loads((fake.root / "state.json").read_text())
    assert state_after["LoadState"] == state_before["LoadState"]


def test_shell_cleanup_stays_bound_to_integration_manifest(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    fake.seed()
    assert len(USER_ASSETS) == 7
    result, commands = fake.run("--yes")
    assert result.returncode == 0, result.stderr
    removed = {
        Path(command[-1]).relative_to(fake.home).as_posix()
        for command in commands
        if command[0] == "rm"
    }
    assert removed == {IMAGE, WRAPPER, *USER_ASSETS, f"{STATE}/installed-tag"}
    assert {item.system_path for item in INTEGRATION_FILES if item.system_path} == {
        "/etc/udev/rules.d/70-naga-control.rules"
    }


def test_removes_only_marked_six_character_backups_and_keeps_unknown_contents(
    tmp_path: Path,
) -> None:
    fake = harness(tmp_path)
    fake.seed()
    marked = fake.backup()
    mixed = fake.backup("rollback.def456")
    (mixed / "operator-notes").write_text("retain\n")
    (mixed / ".hidden-notes").write_text("retain hidden\n")
    unmarked = fake.backup("rollback.xyz789", marker=False)
    wrong_pattern = fake.backup("rollback.too-long")
    wrong_marker = fake.backup("rollback.wrg123")
    (wrong_marker / "installer-backup").write_text("not installer-owned\n")
    linked = fake.home / STATE / "rollback.lnk123"
    linked.symlink_to(unmarked, target_is_directory=True)
    snapshots = {
        path: path.read_bytes()
        for directory in (unmarked, wrong_pattern, wrong_marker)
        for path in directory.iterdir()
    }
    result, _ = fake.run("--yes")
    assert result.returncode == 0, result.stderr
    assert not marked.exists()
    assert set(path.name for path in mixed.iterdir()) == {"operator-notes", ".hidden-notes"}
    assert linked.is_symlink()
    for path, content in snapshots.items():
        assert path.read_bytes() == content


@pytest.mark.parametrize(
    "arguments,reply,remove",
    [((), "n\n", False), ((), "", False), ((), "yes\n", True), (("--yes",), "", True)],
)
def test_optional_udev_consent_is_separate_from_profile_purge(
    tmp_path: Path, arguments: tuple[str, ...], reply: str, remove: bool
) -> None:
    fake = harness(tmp_path)
    fake.seed()
    fake.rule.parent.mkdir()
    fake.rule.write_text("scoped rule\n")
    result, commands = fake.run(*arguments, reply=reply)
    assert result.returncode == 0, result.stderr
    assert fake.rule.exists() != remove
    assert (fake.home / PROFILES).is_file()
    sudo = [command for command in commands if command[0] == "sudo"]
    assert sudo == (
        [["sudo", "rm", "-f", str(fake.rule)], ["sudo", "udevadm", "control", "--reload"]]
        if remove
        else []
    )


def test_purge_is_explicit_and_does_not_follow_descendant_profile_symlinks(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    fake.seed()
    outside = fake.root / "outside-profile"
    outside.write_text("retain\n")
    (fake.home / PROFILES).parent.joinpath("linked-profile").symlink_to(outside)
    result, _ = fake.run("--purge-config", reply="n\n")
    assert result.returncode == 0, result.stderr
    assert not (fake.home / PROFILES).parent.exists()
    assert outside.read_text() == "retain\n"


def test_absent_unit_requires_working_manager_and_verified_inactive_state(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    fake.seed(image=False)
    fake.configure(ActiveState="inactive", UnitFileState="", LoadState="not-found")
    result, commands = fake.run("--yes")
    assert result.returncode == 0, result.stderr
    assert not any(
        command[:3] == ["systemctl", "--user", "stop"] or "disable" in command
        for command in commands
    )
    assert ["systemctl", "--user", "daemon-reload"] in commands


def test_declined_udev_removal_does_not_require_sudo(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    fake.seed()
    fake.rule.parent.mkdir()
    fake.rule.write_text("retain rule\n")
    (fake.root / "bin/sudo").unlink()
    result, commands = fake.run(reply="n\n")
    assert result.returncode == 0, result.stderr
    assert fake.rule.read_text() == "retain rule\n"
    assert not any(command[0] == "sudo" for command in commands)
