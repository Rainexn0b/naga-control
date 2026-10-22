"""Session uninstall happy paths with closed-PATH fakes."""

from pathlib import Path

from tests.session_uninstaller_fakes import (
    ACTIVATION,
    GUI_AUTOSTART,
    HELPER,
    IMAGE,
    MODE,
    PROFILES,
    SERVICE_AUTOSTART,
    STATE,
    WRAPPER,
    dbus_methods,
    session_harness,
)


def test_active_owner_fence_reload_before_prepare_and_removes_owned(tmp_path: Path) -> None:
    fake = session_harness(
        tmp_path,
        {
            "has_owner": True,
            "getowner": ":1.50",
            "after_unique_owner": False,
            "after_well_owner": False,
        },
    )
    contents = fake.seed_session(has_owner=True)
    fake.lock.parent.mkdir(parents=True, exist_ok=True)
    fake.lock.write_text("stable lock\n")
    fake.lock.chmod(0o600)
    lock_inode = fake.lock.stat().st_ino
    result, commands = fake.run("--yes")
    assert result.returncode == 0, result.stderr
    assert "uninstall complete" in result.stdout
    for relative in (IMAGE, WRAPPER, f"{STATE}/installed-tag", MODE, HELPER, ACTIVATION):
        assert not (fake.home / relative).exists(), relative
    assert not (fake.home / SERVICE_AUTOSTART).exists()
    assert not (fake.home / GUI_AUTOSTART).exists()
    assert (fake.home / PROFILES).read_bytes() == contents[PROFILES]
    assert fake.lock.is_file()
    assert fake.lock.stat().st_ino == lock_inode
    assert fake.lock.read_text() == "stable lock\n"
    assert (fake.root / "fd9-leak.log").read_text() == ""
    assert (fake.root / "fd9-leak.log").read_text() == ""
    assert (fake.root / "attempts.log").read_text() == ""
    assert not any(cmd[0] in {"systemctl", "busctl", "python", "python3"} for cmd in commands)
    assert not any("systemctl" in " ".join(cmd) for cmd in commands)
    calls = fake.dbus_calls()
    found = dbus_methods(calls)
    assert "org.freedesktop.DBus.ReloadConfig" in found
    assert "org.nagacontrol.Service1.PrepareShutdown" in found
    assert "org.nagacontrol.Service1.Exit" in found
    assert found.index("org.freedesktop.DBus.ReloadConfig") < found.index(
        "org.nagacontrol.Service1.PrepareShutdown"
    )
    assert found.index("org.nagacontrol.Service1.PrepareShutdown") < found.index(
        "org.nagacontrol.Service1.Exit"
    )
    # Prepare and Exit target the captured unique owner only.
    for args in calls:
        if "org.nagacontrol.Service1.PrepareShutdown" in args:
            assert "--dest=:1.50" in args
        if "org.nagacontrol.Service1.Exit" in args:
            assert "--dest=:1.50" in args
    assert "ReleaseAll" not in str(calls)


def test_absent_owner_succeeds_without_prepare_or_exit(tmp_path: Path) -> None:
    fake = session_harness(tmp_path, {"has_owner": False})
    contents = fake.seed_session(has_owner=False)
    result, _ = fake.run("--yes")
    assert result.returncode == 0, result.stderr
    assert "uninstall complete" in result.stdout
    for relative in (IMAGE, WRAPPER, MODE, HELPER, ACTIVATION):
        assert not (fake.home / relative).exists(), relative
    assert (fake.home / PROFILES).read_bytes() == contents[PROFILES]
    found = dbus_methods(fake.dbus_calls())
    assert "org.nagacontrol.Service1.PrepareShutdown" not in found
    assert "org.nagacontrol.Service1.Exit" not in found
    assert "org.freedesktop.DBus.ReloadConfig" in found


def test_gui_and_service_entries_distinct_and_foreign_preserved(tmp_path: Path) -> None:
    fake = session_harness(tmp_path)
    fake.seed_session()
    other = fake.home / ".config/autostart/other-app.desktop"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("[Desktop Entry]\nType=Application\nExec=/usr/bin/other\n")
    result, _ = fake.run("--yes")
    assert result.returncode == 0, result.stderr
    assert not (fake.home / SERVICE_AUTOSTART).exists()
    assert not (fake.home / GUI_AUTOSTART).exists()
    assert other.read_text() == "[Desktop Entry]\nType=Application\nExec=/usr/bin/other\n"
    assert (fake.home / ".config/autostart").is_dir()


def test_profiles_preserved_unless_purge(tmp_path: Path) -> None:
    fake = session_harness(tmp_path / "keep")
    contents = fake.seed_session()
    result, _ = fake.run("--yes")
    assert result.returncode == 0, result.stderr
    assert (fake.home / PROFILES).read_bytes() == contents[PROFILES]

    fake2 = session_harness(tmp_path / "purge")
    fake2.seed_session()
    result2, _ = fake2.run("--yes", "--purge-config", reply="n\n")
    assert result2.returncode == 0, result2.stderr
    assert not (fake2.home / ".config/naga-control").exists()


def test_never_executes_image_wrapper_or_python(tmp_path: Path) -> None:
    fake = session_harness(tmp_path)
    fake.seed_session()
    result, commands = fake.run("--yes")
    assert result.returncode == 0, result.stderr
    assert (fake.root / "attempts.log").read_text() == ""
    assert not any(
        cmd[0] in {"python", "python3", "naga-control.AppImage", "naga-control"} for cmd in commands
    )


def test_missing_activation_still_stops_and_removes(tmp_path: Path) -> None:
    fake = session_harness(tmp_path)
    fake.seed_session()
    (fake.home / ACTIVATION).unlink()
    result, _ = fake.run("--yes")
    assert result.returncode == 0, result.stderr
    assert "uninstall complete" in result.stdout
    # Files that should be gone are gone; profiles retained.
    assert not (fake.home / IMAGE).exists()
    assert (fake.home / PROFILES).is_file()
