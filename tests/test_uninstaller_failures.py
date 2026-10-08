"""Fail closed before unsafe cleanup; report partial removals without false success."""

import os
from pathlib import Path

import pytest

from tests.uninstaller_fakes import (
    IMAGE,
    OWNED,
    PROFILES,
    STATE,
    USER_ASSETS,
    WRAPPER,
    assert_no_cleanup,
    assert_retained,
    harness,
)


@pytest.mark.parametrize(
    "changes,cause",
    [
        ({"manager_failure": True}, "user systemd unavailable"),
        ({"query_failure": "ActiveState"}, "could not query"),
        ({"query_failure": "UnitFileState"}, "unit enable state"),
        ({"query_failure_after_stop": True}, "could not verify"),
        ({"unit_failure": "stop"}, "Naga stop failed"),
        ({"unit_failure": "disable"}, "Naga disable failed"),
        *[
            ({"stop_state": state}, "not inactive")
            for state in ("active", "deactivating", "failed", "")
        ],
        *[
            ({"ActiveState": state}, "unsafe Naga service state")
            for state in ("unknown", "failed", "deactivating", "")
        ],
        ({"disable_state": "active"}, "not inactive"),
        ({"UnitFileState": "masked"}, "unsafe Naga unit enable state"),
        (
            {"ActiveState": "inactive", "UnitFileState": "", "LoadState": "unknown"},
            "unknown Naga unit state",
        ),
        (
            {"ActiveState": "active", "UnitFileState": "", "LoadState": "not-found"},
            "unknown Naga unit state",
        ),
        ({"UnitFileState": "", "query_failure": "LoadState"}, "missing Naga unit"),
    ],
)
def test_service_unknown_stop_or_disable_failure_preserves_every_file(
    tmp_path: Path, changes: dict[str, object], cause: str
) -> None:
    fake = harness(tmp_path)
    contents = fake.seed()
    backup = fake.backup()
    saved_backup = {path: path.read_bytes() for path in backup.iterdir()}
    fake.configure(**changes)
    result, commands = fake.run("--yes", "--purge-config")
    assert result.returncode != 0
    assert cause in result.stderr
    assert "manual recovery required" in result.stderr
    assert "uninstall complete" not in result.stdout
    assert "removed AppImage" not in result.stdout
    assert_retained(fake, contents)
    for path, content in saved_backup.items():
        assert path.read_bytes() == content
    assert_no_cleanup(commands)


@pytest.mark.parametrize("relative", [IMAGE, WRAPPER, *USER_ASSETS, f"{STATE}/installed-tag"])
def test_symlink_owned_target_refused_before_any_service_call(
    tmp_path: Path, relative: str
) -> None:
    fake = harness(tmp_path)
    contents = fake.seed()
    outside = fake.root / "outside-file"
    outside.write_bytes(contents[relative])
    target = fake.home / relative
    target.unlink()
    target.symlink_to(outside)
    result, commands = fake.run("--yes")
    assert result.returncode != 0
    assert "symlink" in result.stderr
    assert_retained(fake, contents)
    assert target.is_symlink()
    assert not any(command[0] == "systemctl" for command in commands)
    assert_no_cleanup(commands)


@pytest.mark.parametrize(
    "relative", [".local", ".config", ".local/share/icons/hicolor/512x512/apps"]
)
def test_symbolic_ancestor_never_traversed_for_cleanup(tmp_path: Path, relative: str) -> None:
    fake = harness(tmp_path)
    contents = fake.seed()
    ancestor = fake.home / relative
    outside = fake.root / "outside-directory"
    ancestor.rename(outside)
    ancestor.symlink_to(outside, target_is_directory=True)
    result, commands = fake.run("--yes")
    assert result.returncode != 0
    assert "symlink" in result.stderr
    assert_retained(fake, contents)
    assert ancestor.is_symlink()
    assert not any(command[0] == "systemctl" for command in commands)
    assert_no_cleanup(commands)


@pytest.mark.parametrize(
    "kind",
    ["target-directory", "target-fifo", "profile-symlink", "backup-symlink", "udev-symlink"],
)
def test_all_cleanup_targets_are_preflighted_before_stop(tmp_path: Path, kind: str) -> None:
    fake = harness(tmp_path)
    contents = fake.seed()
    if kind in {"target-directory", "target-fifo"}:
        path = fake.home / USER_ASSETS[-1]
        path.unlink()
        if kind == "target-directory":
            path.mkdir()
        else:
            os.mkfifo(path)
        contents.pop(USER_ASSETS[-1])
    elif kind == "profile-symlink":
        path = (fake.home / PROFILES).parent
        outside = fake.root / "outside-profiles"
        path.rename(outside)
        path.symlink_to(outside, target_is_directory=True)
    elif kind == "backup-symlink":
        path = fake.backup() / "naga-control.AppImage"
        path.unlink()
        path.symlink_to(fake.home / IMAGE)
    else:
        fake.rule.parent.mkdir()
        fake.rule.symlink_to(fake.home / IMAGE)
    result, commands = fake.run("--yes", "--purge-config")
    assert result.returncode != 0
    assert_retained(fake, contents)
    assert not any(command[0] == "systemctl" for command in commands)
    assert_no_cleanup(commands)


@pytest.mark.parametrize(
    "home", ["", "/", "relative", "dot-components", "symlink", "ancestor-symlink"]
)
def test_home_is_absolute_and_has_no_symbolic_ancestors(tmp_path: Path, home: str) -> None:
    fake = harness(tmp_path)
    contents = fake.seed()
    if home == "dot-components":
        home = str(fake.home) + "/../home"
    elif home == "symlink":
        link = fake.root / "linked-home"
        link.symlink_to(fake.home, target_is_directory=True)
        home = str(link)
    elif home == "ancestor-symlink":
        link = fake.root / "linked-parent"
        link.symlink_to(fake.root, target_is_directory=True)
        home = str(link / "home")
    fake.environment["HOME"] = home
    result, commands = fake.run("--yes")
    assert result.returncode != 0
    assert_retained(fake, contents)
    assert_no_cleanup(commands)
    assert not any(command[0] == "systemctl" for command in commands)


def test_even_a_known_target_outside_home_is_rejected(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    contents = fake.seed()
    outside = fake.root / "outside-image"
    outside.write_text("keep\n")
    source = fake.script.read_text()
    fake.script.write_text(
        source.replace(
            'APPIMAGE_DST="$HOME/.local/bin/naga-control.AppImage"', f'APPIMAGE_DST="{outside}"'
        )
    )
    result, commands = fake.run("--yes")
    assert result.returncode != 0
    assert "outside HOME" in result.stderr
    assert outside.read_text() == "keep\n"
    assert_retained(fake, contents)
    assert_no_cleanup(commands)


@pytest.mark.parametrize(
    "failure", ["image", "icon", "rmdir", "profiles", "daemon-reload", "udev-remove", "udev-reload"]
)
def test_cleanup_failure_is_truthful_and_preserves_first_cause(
    tmp_path: Path, failure: str
) -> None:
    fake = harness(tmp_path)
    fake.seed()
    backup = fake.backup()
    fake.rule.parent.mkdir()
    fake.rule.write_text("rule retained unless removed\n")
    if failure in {"image", "icon", "profiles"}:
        relative = {"image": IMAGE, "icon": USER_ASSETS[-1], "profiles": ".config/naga-control"}[
            failure
        ]
        fake.configure(rm_failure=str(fake.home / relative))
        cause = "fake rm failure"
    elif failure == "rmdir":
        fake.configure(rmdir_failure=str(backup))
        cause = "fake rmdir failure"
    elif failure == "daemon-reload":
        fake.configure(unit_failure="daemon-reload")
        cause = "fake daemon-reload failure"
    elif failure == "udev-remove":
        fake.configure(sudo_rm_failure=True)
        cause = "fake sudo rm failure"
    else:
        fake.configure(udev_failure=True)
        cause = "fake udev reload failure"
    result, _ = fake.run("--yes", "--purge-config")
    assert result.returncode != 0
    assert cause in result.stderr
    assert "uninstall complete" not in result.stdout
    assert fake.lock.is_file()
    if failure == "image":
        assert all((fake.home / relative).exists() for relative in OWNED)
    elif failure == "icon":
        assert not (fake.home / IMAGE).exists()
        assert (fake.home / USER_ASSETS[-1]).is_file()
        assert "earlier removals are not rolled back" in result.stderr
    elif failure == "profiles":
        assert (fake.home / PROFILES).is_file()
    elif failure == "udev-remove":
        assert fake.rule.is_file()
        assert "no system rollback" in result.stderr
    elif failure == "udev-reload":
        assert not fake.rule.exists()
        assert "permissions pending" in result.stderr
        assert "removed udev rule and reloaded" not in result.stdout
    if failure != "profiles":
        assert (fake.home / PROFILES).is_file()


@pytest.mark.parametrize("failure", ["root", "missing-systemctl", "missing-flock"])
def test_root_or_missing_required_tool_fails_without_cleanup(tmp_path: Path, failure: str) -> None:
    fake = harness(tmp_path)
    contents = fake.seed()
    if failure == "root":
        fake.configure(uid="0")
    else:
        (fake.root / "bin" / failure.removeprefix("missing-")).unlink()
    result, commands = fake.run("--yes")
    assert result.returncode != 0
    assert_retained(fake, contents)
    assert_no_cleanup(commands)
    assert not fake.lock.exists()


@pytest.mark.parametrize("missing", ["sudo", "udevadm"])
def test_missing_consented_udev_tool_reports_partial_cleanup(tmp_path: Path, missing: str) -> None:
    fake = harness(tmp_path)
    fake.seed()
    fake.rule.parent.mkdir()
    fake.rule.write_text("retain rule\n")
    (fake.root / "bin" / missing).unlink()
    result, commands = fake.run("--yes")
    assert result.returncode != 0
    assert missing + " is required" in result.stderr
    assert "user files already removed, rule retained" in result.stderr
    assert "uninstall complete" not in result.stdout
    assert fake.rule.read_text() == "retain rule\n"
    assert (fake.home / PROFILES).is_file()
    assert not any(command[0] == "sudo" for command in commands)
