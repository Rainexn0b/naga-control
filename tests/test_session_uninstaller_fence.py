"""Fence ownership: unique temps, backups, Hidden fence, final reload."""

from pathlib import Path

from tests.session_uninstaller_fakes import (
    ACTIVATION,
    HELPER,
    IMAGE,
    MODE,
    SERVICE_AUTOSTART,
    STATE,
    SessionUninstallerHarness,
    dbus_methods,
    session_harness,
)

BLOCKER = "[D-BUS Service]\nName=org.nagacontrol.Service1\nExec=/bin/false\n"


def _backups(fake: SessionUninstallerHarness, prefix: str) -> list[Path]:
    return sorted((fake.home / STATE).glob(f".session-uninstall.{prefix}.*"))


def test_predictable_fence_tmp_and_hardlink_preserved(tmp_path: Path) -> None:
    fake = session_harness(tmp_path)
    fake.seed_session()
    fence_dir = fake.home / ".local/share/dbus-1/services"
    predictable = fence_dir / ".naga-fence.tmp"
    predictable.write_text("sentinel-regular\n")
    predictable.chmod(0o600)
    link_src = fake.root / "sentinel-src"
    link_src.write_text("sentinel-hardlink\n")
    import os

    hardlink = fence_dir / ".naga-fence.tmp-hardlink"
    try:
        os.link(link_src, hardlink)
        has_hardlink = True
    except OSError:
        has_hardlink = False
    result, _ = fake.run("--yes")
    assert result.returncode == 0, result.stderr
    assert predictable.read_text() == "sentinel-regular\n"
    if has_hardlink:
        assert hardlink.read_text() == "sentinel-hardlink\n"
    # Unique fence was used; no leftover predictable temp confusion.
    assert not (fake.home / ACTIVATION).exists()
    assert _backups(fake, "activation") == []
    assert _backups(fake, "autostart") == []


def test_prepare_failure_keeps_byte_exact_backup(tmp_path: Path) -> None:
    original = (
        "[D-BUS Service]\nName=org.nagacontrol.Service1\nExec=/tmp/custom-launcher service --flag\n"
    )
    fake = session_harness(tmp_path, {"has_owner": True, "prepare_fail": True})
    contents = fake.seed_session()
    (fake.home / ACTIVATION).write_text(original)
    result, commands = fake.run("--yes")
    assert result.returncode != 0
    assert "uninstall complete" not in result.stdout
    found = dbus_methods(fake.dbus_calls())
    assert "org.nagacontrol.Service1.PrepareShutdown" in found
    assert "org.nagacontrol.Service1.Exit" not in found
    assert not any(cmd[0] in {"rm", "rmdir"} for cmd in commands)
    backups = _backups(fake, "activation")
    assert len(backups) == 1
    assert backups[0].read_bytes() == original.encode()
    assert (fake.home / ACTIVATION).read_text() == BLOCKER
    for relative in (IMAGE, MODE, HELPER):
        assert (fake.home / relative).read_bytes() == contents[relative]
    auto_backups = _backups(fake, "autostart")
    assert len(auto_backups) == 1
    assert str(backups[0]) in result.stderr
    assert str(auto_backups[0]) in result.stderr


def test_prepare_observes_hidden_true_before_cleanup(tmp_path: Path) -> None:
    fake = session_harness(tmp_path)
    fake.seed_session()
    result, _ = fake.run("--yes")
    assert result.returncode == 0, result.stderr
    log = (fake.root / "prepare_hidden.log").read_text().splitlines()
    assert log and all(line == "hidden" for line in log)
    assert not (fake.home / SERVICE_AUTOSTART).exists()


def test_final_reload_after_removal_before_complete(tmp_path: Path) -> None:
    fake = session_harness(tmp_path)
    fake.seed_session()
    result, _ = fake.run("--yes")
    assert result.returncode == 0, result.stderr
    found = dbus_methods(fake.dbus_calls())
    reloads = [i for i, m in enumerate(found) if m == "org.freedesktop.DBus.ReloadConfig"]
    assert len(reloads) >= 2
    prepare = found.index("org.nagacontrol.Service1.PrepareShutdown")
    exit_idx = found.index("org.nagacontrol.Service1.Exit")
    assert reloads[0] < prepare < exit_idx < reloads[-1]
    assert not (fake.home / MODE).exists()
    assert not (fake.home / HELPER).exists()
    assert _backups(fake, "activation") == []
    assert _backups(fake, "autostart") == []


def test_final_reload_failure_retains_mode_helper_and_backups(tmp_path: Path) -> None:
    original_act = "[D-BUS Service]\nName=org.nagacontrol.Service1\nExec=/tmp/x service\n"
    original_auto = (
        "[Desktop Entry]\nType=Application\nName=Naga\n"
        "Exec=/tmp/x service\nX-NagaControl-Service=true\n"
    )
    fake = session_harness(tmp_path, {"reload_fail_second": True})
    fake.seed_session()
    (fake.home / ACTIVATION).write_text(original_act)
    (fake.home / SERVICE_AUTOSTART).write_text(original_auto)
    result, _ = fake.run("--yes")
    assert result.returncode != 0
    assert "uninstall complete" not in result.stdout
    assert "incomplete" in result.stderr.lower()
    # Mode/helper retained for honest retry; backups retained.
    assert (fake.home / MODE).read_bytes() == b"session\n"
    assert (fake.home / HELPER).is_file()
    act_backups = _backups(fake, "activation")
    auto_backups = _backups(fake, "autostart")
    assert len(act_backups) == 1
    assert act_backups[0].read_bytes() == original_act.encode()
    assert len(auto_backups) == 1
    assert auto_backups[0].read_bytes() == original_auto.encode()
    assert str(act_backups[0]) in result.stderr
    assert str(auto_backups[0]) in result.stderr


def test_only_own_backup_cleaned_unknown_preserved(tmp_path: Path) -> None:
    fake = session_harness(tmp_path)
    fake.seed_session()
    unknown = fake.home / STATE / ".session-uninstall.activation.UNKNOWN"
    unknown.write_text("concurrent-operator\n")
    unknown.chmod(0o600)
    result, _ = fake.run("--yes")
    assert result.returncode == 0, result.stderr
    assert unknown.read_text() == "concurrent-operator\n"
    assert _backups(fake, "activation") == [unknown]
    # Own backup gone: only the pre-existing unknown remains.
    own = [
        p for p in _backups(fake, "activation") if p.name != ".session-uninstall.activation.UNKNOWN"
    ]
    assert own == []
