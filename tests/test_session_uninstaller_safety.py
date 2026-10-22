"""Session uninstall fail-closed paths with closed-PATH fakes."""

import os
from pathlib import Path

import pytest

from tests.session_uninstaller_fakes import (
    ACTIVATION,
    GUI_AUTOSTART,
    HELPER,
    IMAGE,
    MODE,
    SERVICE_AUTOSTART,
    assert_session_retained,
    dbus_methods,
    session_harness,
)


def test_invalid_mode_fails_before_any_mutation(tmp_path: Path) -> None:
    for kind in ("bogus", "oversize", "empty", "symlink", "directory"):
        fake = session_harness(tmp_path / kind)
        contents = fake.seed_session()
        mode_path = fake.home / MODE
        if kind == "bogus":
            mode_path.write_text("bogus\n")
        elif kind == "oversize":
            mode_path.write_text("session\n extra\n")
        elif kind == "empty":
            mode_path.write_text("")
        elif kind == "symlink":
            outside = fake.root / "outside-mode"
            outside.write_text("session\n")
            mode_path.unlink()
            mode_path.symlink_to(outside)
        else:
            mode_path.unlink()
            mode_path.mkdir()
        result, commands = fake.run("--yes")
        assert result.returncode != 0, kind
        assert "uninstall complete" not in result.stdout
        assert fake.dbus_calls() == []
        assert not any(cmd[0] in {"rm", "rmdir", "sudo", "mv"} for cmd in commands)
        # Owned app files retained; mode itself is retained as-is for recovery.
        for relative in (IMAGE, HELPER, ACTIVATION):
            assert (fake.home / relative).read_bytes() == contents[relative]
        assert mode_path.exists() or mode_path.is_symlink()


def test_unknown_bus_retains_files_and_blocker_without_exit(tmp_path: Path) -> None:
    fake = session_harness(tmp_path, {"bus_available": False})
    contents = fake.seed_session()
    result, commands = fake.run("--yes")
    assert result.returncode != 0
    assert "uninstall complete" not in result.stdout
    for relative in (IMAGE, HELPER, MODE):
        assert (fake.home / relative).read_bytes() == contents[relative]
    found = dbus_methods(fake.dbus_calls())
    assert "org.nagacontrol.Service1.Exit" not in found
    assert not any(cmd[0] in {"rm", "rmdir"} for cmd in commands)
    # Fence wrote the blocker before the bus failure; blocker retained.
    assert (fake.home / ACTIVATION).read_text() == (
        "[D-BUS Service]\nName=org.nagacontrol.Service1\nExec=/bin/false\n"
    )


def test_prepare_failure_retains_all_without_exit(tmp_path: Path) -> None:
    fake = session_harness(tmp_path, {"has_owner": True, "prepare_fail": True})
    contents = fake.seed_session()
    result, commands = fake.run("--yes")
    assert result.returncode != 0
    assert "uninstall complete" not in result.stdout
    for relative in (IMAGE, HELPER, MODE):
        assert (fake.home / relative).read_bytes() == contents[relative]
    found = dbus_methods(fake.dbus_calls())
    assert "org.nagacontrol.Service1.PrepareShutdown" in found
    assert "org.nagacontrol.Service1.Exit" not in found
    assert not any(cmd[0] in {"rm", "rmdir"} for cmd in commands)
    assert (fake.home / IMAGE).is_file()
    assert (fake.home / MODE).read_text() == "session\n"
    assert (fake.home / ACTIVATION).read_text() == (
        "[D-BUS Service]\nName=org.nagacontrol.Service1\nExec=/bin/false\n"
    )


def test_replacement_owner_fails_closed(tmp_path: Path) -> None:
    fake = session_harness(
        tmp_path,
        {
            "has_owner": True,
            "getowner": ":1.50",
            "after_unique_owner": False,
            "after_well_owner": True,
        },
    )
    contents = fake.seed_session()
    result, _ = fake.run("--yes")
    assert result.returncode != 0
    assert "uninstall complete" not in result.stdout
    for relative in (IMAGE, HELPER, MODE):
        assert (fake.home / relative).read_bytes() == contents[relative]
    assert (fake.home / ACTIVATION).read_text() == (
        "[D-BUS Service]\nName=org.nagacontrol.Service1\nExec=/bin/false\n"
    )


def test_reload_failure_happens_before_prepare_and_retains_blocker(tmp_path: Path) -> None:
    fake = session_harness(tmp_path, {"has_owner": True, "reload_fail": True})
    contents = fake.seed_session()
    result, _ = fake.run("--yes")
    assert result.returncode != 0
    found = dbus_methods(fake.dbus_calls())
    assert "org.freedesktop.DBus.ReloadConfig" in found
    assert "org.nagacontrol.Service1.PrepareShutdown" not in found
    assert "org.nagacontrol.Service1.Exit" not in found
    # App files retained; activation is the fence blocker for manual recovery.
    for relative in (IMAGE, MODE, HELPER):
        assert (fake.home / relative).read_bytes() == contents[relative]
    assert (fake.home / ACTIVATION).read_text() == (
        "[D-BUS Service]\nName=org.nagacontrol.Service1\nExec=/bin/false\n"
    )


def test_foreign_activation_fails_before_bus_or_cleanup(tmp_path: Path) -> None:
    fake = session_harness(tmp_path)
    contents = fake.seed_session()
    (fake.home / ACTIVATION).write_text(
        "[D-BUS Service]\nName=org.other.Service\nExec=/usr/bin/other\n"
    )
    result, commands = fake.run("--yes")
    assert result.returncode != 0
    assert fake.dbus_calls() == []
    assert not any(cmd[0] in {"rm", "rmdir", "sudo"} for cmd in commands)
    assert (fake.home / IMAGE).read_bytes() == contents[IMAGE]


@pytest.mark.parametrize("kind", ["foreign", "symlink", "directory"])
def test_service_autostart_foreign_kinds_preserved_with_success(tmp_path: Path, kind: str) -> None:
    fake = session_harness(tmp_path)
    fake.seed_session()
    target = fake.home / SERVICE_AUTOSTART
    if kind == "foreign":
        target.write_text("[Desktop Entry]\nType=Application\nExec=/usr/bin/other\n")
    elif kind == "symlink":
        real = fake.root / "real.desktop"
        real.write_text("[Desktop Entry]\nType=Application\nX-NagaControl-Service=true\n")
        target.unlink()
        target.symlink_to(real)
    else:
        target.unlink()
        target.mkdir()
    result, _ = fake.run("--yes")
    assert result.returncode == 0, result.stderr
    if kind == "symlink":
        assert target.is_symlink()
    elif kind == "directory":
        assert target.is_dir()
    else:
        assert target.is_file()
    assert not (fake.home / IMAGE).exists()


def test_unsafe_owned_service_autostart_fails_before_bus(tmp_path: Path) -> None:
    fake = session_harness(tmp_path)
    contents = fake.seed_session()
    target = fake.home / SERVICE_AUTOSTART
    assert target.is_file()
    target.parent.chmod(0o777)
    try:
        result, commands = fake.run("--yes")
    finally:
        target.parent.chmod(0o755)
    assert result.returncode != 0
    assert fake.dbus_calls() == []
    assert not any(cmd[0] in {"rm", "rmdir", "sudo"} for cmd in commands)
    for relative, data in contents.items():
        assert (fake.home / relative).read_bytes() == data


def test_held_lock_blocks_every_session_mutation(tmp_path: Path) -> None:
    import fcntl

    fake = session_harness(tmp_path)
    contents = fake.seed_session()
    fake.lock.write_text("held lock\n")
    inode = fake.lock.stat().st_ino
    with fake.lock.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result, commands = fake.run("--yes")
        assert result.returncode != 0
        assert "another Naga installer is running" in result.stderr
        assert_session_retained(fake, contents)
        assert fake.dbus_calls() == []
        assert not any(cmd[0] in {"rm", "rmdir", "sudo", "mv"} for cmd in commands)
        assert fake.lock.stat().st_ino == inode


def test_missing_trusted_sibling_fails_before_mutations(tmp_path: Path) -> None:
    fake = session_harness(tmp_path)
    contents = fake.seed_session()
    (fake.root / "session_service.sh").unlink()
    result, commands = fake.run("--yes")
    assert result.returncode != 0
    assert fake.dbus_calls() == []
    assert not any(cmd[0] in {"rm", "rmdir", "sudo"} for cmd in commands)
    assert (fake.home / IMAGE).read_bytes() == contents[IMAGE]
    assert os.path.isfile(fake.home / GUI_AUTOSTART)


def test_missing_bus_address_is_unknown_not_inactive(tmp_path: Path) -> None:
    fake = session_harness(tmp_path)
    contents = fake.seed_session()
    del fake.environment["DBUS_SESSION_BUS_ADDRESS"]
    result, commands = fake.run("--yes")
    assert result.returncode != 0
    assert "uninstall complete" not in result.stdout
    for relative in (IMAGE, HELPER, MODE):
        assert (fake.home / relative).read_bytes() == contents[relative]
    assert fake.dbus_calls() == []
    assert not any(cmd[0] in {"rm", "rmdir"} for cmd in commands)
    assert (fake.home / ACTIVATION).read_text() == (
        "[D-BUS Service]\nName=org.nagacontrol.Service1\nExec=/bin/false\n"
    )
