"""Session fence persistence and verified rollback recovery (fake only)."""

import hashlib
from pathlib import Path

from tests.installer_app_fakes import (
    ASSET,
    app_harness,
    assert_private_cleanup,
    installed_image,
    stamp,
)
from tests.openrazer_installer_fakes import TAG, InstallerHarness

MARKER = ".local/share/naga-control/service-manager"
HELPER = ".local/share/naga-control/session-service.sh"
ACTIVATION = ".local/share/dbus-1/services/org.nagacontrol.Service1.service"
BLOCKER_EXEC = "Exec=/bin/false"


def _autostart(fake: InstallerHarness) -> Path:
    return fake.root / "home/.config/autostart/org.nagacontrol.Service.desktop"


def _seed_session(fake: InstallerHarness, *, active: bool = True) -> bytes:
    old: bytes = fake.remote.joinpath(ASSET).read_bytes()
    image: Path = installed_image(fake)
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(old)
    image.chmod(0o755)
    stamp(fake).parent.mkdir(parents=True, exist_ok=True)
    stamp(fake).write_text("v0.3.0\n")
    marker: Path = fake.root / "home" / MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("session\n")
    marker.chmod(0o600)
    helper_src: Path = fake.root / "checkout/scripts/session_service.sh"
    helper_dst: Path = fake.root / "home" / HELPER
    helper_dst.parent.mkdir(parents=True, exist_ok=True)
    helper_dst.write_bytes(helper_src.read_bytes())
    helper_dst.chmod(0o700)
    activation: Path = fake.root / "home" / ACTIVATION
    activation.parent.mkdir(parents=True, exist_ok=True)
    activation.write_text(
        "[D-BUS Service]\nName=org.nagacontrol.Service1\nExec=" + str(image) + " service\n"
    )
    autostart: Path = _autostart(fake)
    autostart.parent.mkdir(parents=True, exist_ok=True)
    autostart.write_text(
        "[Desktop Entry]\nType=Application\nName=Naga Control background service\nExec="
        + str(image)
        + " service\nHidden=false\nX-NagaControl-Service=true\n"
    )
    fake.remote.joinpath(ASSET).write_bytes(old + b"\n# updated fixture\n")
    fake.configure(previous_tag="v0.3.0", previous_digest=hashlib.sha256(old).hexdigest())
    fake.remote.joinpath(ASSET + ".sha256").write_text(
        hashlib.sha256(fake.remote.joinpath(ASSET).read_bytes()).hexdigest() + "  " + ASSET + "\n"
    )
    fake.configure(has_owner=active, bus_available=True)
    fake.configure(service_state="inactive", unit_state="")
    return old


def _recoveries(fake: InstallerHarness) -> list[Path]:
    parent: Path = fake.root / "home/.local/share/naga-control"
    if not parent.is_dir():
        return []
    return sorted(parent.glob("session-recovery.*"))


def _rollbacks(fake: InstallerHarness) -> list[Path]:
    parent: Path = fake.root / "home/.local/share/naga-control"
    if not parent.is_dir():
        return []
    return sorted(parent.glob("rollback.*"))


def test_reload_failure_keeps_fence_hidden_and_snapshot(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    previous: bytes = _seed_session(fake, active=True)
    orig_activation: str = (fake.root / "home" / ACTIVATION).read_text()
    orig_autostart: str = _autostart(fake).read_text()
    orig_marker: str = (fake.root / "home" / MARKER).read_text()
    orig_helper: bytes = (fake.root / "home" / HELPER).read_bytes()
    fake.configure(reload_fail=True)
    result, _ = fake.run(
        "--version", TAG, "--service-manager", "session", "--restart-service", script=script
    )
    assert result.returncode != 0
    assert "fenced" in result.stderr
    assert installed_image(fake).read_bytes() == previous
    live_activation: str = (fake.root / "home" / ACTIVATION).read_text()
    assert BLOCKER_EXEC in live_activation
    assert "org.nagacontrol.Service1" in live_activation
    live_autostart: str = _autostart(fake).read_text()
    assert "Hidden=true" in live_autostart
    assert "X-NagaControl-Service=true" in live_autostart
    assert "Type=Application" in live_autostart
    snapshots: list[Path] = _recoveries(fake)
    assert len(snapshots) == 1
    snap: Path = snapshots[0]
    assert (snap / "activation.service").read_text() == orig_activation
    assert (snap / "autostart.desktop").read_text() == orig_autostart
    assert (snap / "service-manager").read_text() == orig_marker
    assert (snap / "session-service.sh").read_bytes() == orig_helper
    assert "operator recovery snapshot retained" in result.stderr
    assert _rollbacks(fake) == []
    assert_private_cleanup(fake)


def test_prepare_failure_keeps_fence_and_snapshot(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    previous: bytes = _seed_session(fake, active=True)
    orig_activation: str = (fake.root / "home" / ACTIVATION).read_text()
    fake.configure(prepare_fail=True)
    result, _ = fake.run(
        "--version", TAG, "--service-manager", "session", "--restart-service", script=script
    )
    assert result.returncode != 0
    assert "fenced" in result.stderr or "stop failed" in result.stderr
    assert installed_image(fake).read_bytes() == previous
    assert BLOCKER_EXEC in (fake.root / "home" / ACTIVATION).read_text()
    assert "Hidden=true" in _autostart(fake).read_text()
    snapshots: list[Path] = _recoveries(fake)
    assert len(snapshots) == 1
    assert (snapshots[0] / "activation.service").read_text() == orig_activation
    assert "operator recovery snapshot retained" in result.stderr
    assert_private_cleanup(fake)


def test_verified_start_failure_once_restores_full_metadata(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    previous: bytes = _seed_session(fake, active=True)
    orig_activation: str = (fake.root / "home" / ACTIVATION).read_text()
    orig_autostart: str = _autostart(fake).read_text()
    orig_helper: bytes = (fake.root / "home" / HELPER).read_bytes()
    fake.configure(start_fail_once=True)
    result, _ = fake.run(
        "--version", TAG, "--service-manager", "session", "--restart-service", script=script
    )
    assert result.returncode != 0
    assert "start failed" in result.stderr
    assert installed_image(fake).read_bytes() == previous
    assert (fake.root / "home" / MARKER).read_text() == "session\n"
    assert (fake.root / "home" / HELPER).read_bytes() == orig_helper
    assert (fake.root / "home" / ACTIVATION).read_text() == orig_activation
    assert _autostart(fake).read_text() == orig_autostart
    assert BLOCKER_EXEC not in (fake.root / "home" / ACTIVATION).read_text()
    backups: list[Path] = _rollbacks(fake)
    assert len(backups) == 1
    names: list[str] = sorted(p.name for p in backups[0].iterdir())
    assert names == sorted(
        ["image.sha256", "installer-backup", "installed-tag", "naga-control.AppImage"]
    )
    assert (backups[0] / "naga-control.AppImage").read_bytes() == previous
    assert_private_cleanup(fake)


def test_verified_start_failure_persistent_keeps_fence(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    previous: bytes = _seed_session(fake, active=True)
    fake.configure(start_fail=True)
    result, _ = fake.run(
        "--version", TAG, "--service-manager", "session", "--restart-service", script=script
    )
    assert result.returncode != 0
    assert installed_image(fake).read_bytes() == previous
    assert BLOCKER_EXEC in (fake.root / "home" / ACTIVATION).read_text()
    assert len(_recoveries(fake)) == 1
    assert len(_rollbacks(fake)) == 1
    assert "operator recovery snapshot retained" in result.stderr
    assert_private_cleanup(fake)


def test_unverified_post_replace_failure_never_resumes(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    _seed_session(fake, active=True)
    installed_image(fake).write_bytes(b"tampered-local\n")
    fake.configure(start_fail=True)
    result, _ = fake.run(
        "--version", TAG, "--service-manager", "session", "--restart-service", script=script
    )
    assert result.returncode != 0
    assert "unverified" in result.stderr.lower()
    assert "fenced" in result.stderr.lower()
    assert BLOCKER_EXEC in (fake.root / "home" / ACTIVATION).read_text()
    assert len(_recoveries(fake)) == 1
    assert _rollbacks(fake) == []
    assert "operator recovery snapshot retained" in result.stderr
    assert_private_cleanup(fake)
