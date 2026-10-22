"""Session fresh/auto selection and happy-path upgrades (fake only)."""

import hashlib
import stat
from pathlib import Path

from tests.installer_app_fakes import (
    ASSET,
    app_harness,
    assert_private_cleanup,
    installed_image,
    mutations,
    seed_previous,
    stamp,
)
from tests.openrazer_installer_fakes import TAG, InstallerHarness

MARKER = ".local/share/naga-control/service-manager"
HELPER = ".local/share/naga-control/session-service.sh"
ACTIVATION = ".local/share/dbus-1/services/org.nagacontrol.Service1.service"


def _config_autostart(fake: InstallerHarness) -> Path:
    base: Path = fake.root / "home"
    return base / ".config/autostart/org.nagacontrol.Service.desktop"


def _seed_session(fake: InstallerHarness, *, tag: str = "v0.3.0", active: bool = True) -> bytes:
    old: bytes = fake.remote.joinpath(ASSET).read_bytes()
    image: Path = installed_image(fake)
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(old)
    image.chmod(0o755)
    stamp(fake).parent.mkdir(parents=True, exist_ok=True)
    stamp(fake).write_text(tag + "\n")
    marker = fake.root / "home" / MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("session\n")
    marker.chmod(0o600)
    helper_src = fake.root / "checkout/scripts/session_service.sh"
    helper_dst = fake.root / "home" / HELPER
    helper_dst.parent.mkdir(parents=True, exist_ok=True)
    helper_dst.write_bytes(helper_src.read_bytes())
    helper_dst.chmod(0o700)
    activation = fake.root / "home" / ACTIVATION
    activation.parent.mkdir(parents=True, exist_ok=True)
    activation.write_text(
        "[D-BUS Service]\nName=org.nagacontrol.Service1\nExec=" + str(image) + " service\n"
    )
    autostart = _config_autostart(fake)
    autostart.parent.mkdir(parents=True, exist_ok=True)
    autostart.write_text(
        "[Desktop Entry]\nType=Application\nName=Naga Control background service\nExec="
        + str(image)
        + " service\nHidden=false\nX-NagaControl-Service=true\n"
    )
    for relative in (
        ".local/bin/naga-control",
        ".local/share/applications/org.nagacontrol.NagaControl.desktop",
        *(
            f".local/share/icons/hicolor/{s}x{s}/apps/org.nagacontrol.NagaControl.png"
            for s in (64, 128, 256, 512)
        ),
    ):
        target = fake.root / "home" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("previous session integration\n")

    fake.remote.joinpath(ASSET).write_bytes(old + b"\n# updated fixture\n")
    fake.configure(previous_tag=tag, previous_digest=hashlib.sha256(old).hexdigest())
    fake.remote.joinpath(ASSET + ".sha256").write_text(
        hashlib.sha256(fake.remote.joinpath(ASSET).read_bytes()).hexdigest() + "  " + ASSET + "\n"
    )
    fake.configure(has_owner=active, bus_available=True)
    fake.configure(service_state="inactive", unit_state="")
    return old


def test_fresh_auto_falls_back_to_session_when_systemd_unusable(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    fake.configure(systemd_failure=1, bus_failure=1, bus_available=True, has_owner=False)
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "service manager: session" in result.stdout
    assert (fake.root / "home" / MARKER).read_text() == "session\n"
    assert (fake.root / "home" / HELPER).is_file()
    assert "SystemdService=" not in (fake.root / "home" / ACTIVATION).read_text()
    assert _config_autostart(fake).is_file()
    assert not any(c[0] == "systemctl" and c[1] != "--user" for c in commands)
    assert not any(c[0] == "installer-helper" for c in commands)
    assert_private_cleanup(fake)


def test_fresh_auto_missing_systemctl_enters_session(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    (fake.root / "bin/systemctl").unlink()
    (fake.root / "bin/busctl").unlink()
    fake.configure(bus_available=True, has_owner=False)
    result, _ = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "service manager: session" in result.stdout
    assert (fake.root / "home" / MARKER).read_text() == "session\n"
    assert_private_cleanup(fake)


def test_forced_systemd_still_fails_when_manager_unusable(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    fake.configure(systemd_failure=1)
    result, commands = fake.run("--version", TAG, "--service-manager", "systemd", script=script)
    assert result.returncode != 0
    assert "user systemd unavailable" in result.stderr
    assert mutations(commands) == []
    assert_private_cleanup(fake)


def test_explicit_session_needs_no_systemctl_or_busctl(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    fake.configure(bus_available=True, has_owner=False)
    result, commands = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode == 0, result.stderr
    assert not any(c[0] == "systemctl" for c in commands)
    assert not any(c[0] == "busctl" for c in commands)
    assert any(c[0] == "dbus-send" for c in commands)
    assert (fake.root / "home" / MARKER).read_text() == "session\n"
    assert_private_cleanup(fake)


def test_session_fresh_install_writes_private_marker_helper(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    fake.configure(bus_available=True, has_owner=False)
    result, _ = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode == 0, result.stderr
    marker = fake.root / "home" / MARKER
    helper = fake.root / "home" / HELPER
    assert marker.read_text() == "session\n"
    assert stat.S_IMODE(marker.stat().st_mode) == 0o600
    assert helper.is_file() and not helper.is_symlink()
    assert stat.S_IMODE(helper.stat().st_mode) in (0o600, 0o700)
    assert "SystemdService=" not in (fake.root / "home" / ACTIVATION).read_text()
    autostart = _config_autostart(fake)
    assert "X-NagaControl-Service=true" in autostart.read_text()
    assert_private_cleanup(fake)


def test_pinned_systemd_preserved_under_auto(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    seed_previous(fake)
    result, commands = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    assert "service manager: systemd" in result.stdout
    assert (fake.root / "home" / MARKER).read_text() == "systemd\n"
    assert ["systemctl", "--user", "enable", "--now", "naga-control.service"] in commands
    assert_private_cleanup(fake)


def test_session_upgrade_keeps_verified_rollback_with_mode_snapshot(
    tmp_path: Path,
) -> None:
    fake, script = app_harness(tmp_path)
    previous = _seed_session(fake, active=False)
    image = installed_image(fake)
    inode = image.stat().st_ino
    result, _ = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode == 0, result.stderr
    assert image.stat().st_ino != inode
    assert image.read_bytes() == (fake.remote / ASSET).read_bytes()
    backups = list((fake.root / "home/.local/share/naga-control").glob("rollback.*"))
    assert len(backups) == 1
    names = sorted(p.name for p in backups[0].iterdir())
    assert names == sorted(
        [
            "naga-control.AppImage",
            "installed-tag",
            "image.sha256",
            "installer-backup",
        ]
    )
    assert (backups[0] / "naga-control.AppImage").read_bytes() == previous
    assert (fake.root / "home" / MARKER).read_text() == "session\n"
    assert (fake.root / "home" / HELPER).is_file()
    assert "SystemdService=" not in (fake.root / "home" / ACTIVATION).read_text()
    assert_private_cleanup(fake)


def test_session_udev_pending_does_not_start(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    fake.configure(bus_available=True, has_owner=False, udev_failure=1)
    result, _ = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode == 0, result.stderr
    assert "installation staged:" in result.stdout
    assert "service running" not in result.stdout
    assert_private_cleanup(fake)
