"""Transaction authority: mode revalidation under lock + systemd XDG (fakes)."""

from __future__ import annotations

import hashlib
import shutil
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


def _seed_session(fake: InstallerHarness, *, active: bool = False) -> bytes:
    old: bytes = fake.remote.joinpath(ASSET).read_bytes()
    image: Path = installed_image(fake)
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(old)
    image.chmod(0o755)
    stamp(fake).parent.mkdir(parents=True, exist_ok=True)
    stamp(fake).write_text("v0.3.0\n")
    marker: Path = fake.root / "home/.local/share/naga-control/service-manager"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("session\n")
    marker.chmod(0o600)
    helper_src: Path = fake.root / "checkout/scripts/session_service.sh"
    helper_dst: Path = fake.root / "home/.local/share/naga-control/session-service.sh"
    helper_dst.parent.mkdir(parents=True, exist_ok=True)
    helper_dst.write_bytes(helper_src.read_bytes())
    helper_dst.chmod(0o700)
    activation: Path = (
        fake.root / "home/.local/share/dbus-1/services/org.nagacontrol.Service1.service"
    )
    activation.parent.mkdir(parents=True, exist_ok=True)
    activation.write_text(
        "[D-BUS Service]\nName=org.nagacontrol.Service1\nExec=" + str(image) + " service\n"
    )
    autostart: Path = fake.root / "home/.config/autostart/org.nagacontrol.Service.desktop"
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


def _wrap_flock_set_mode(fake: InstallerHarness, value: str | None) -> Path:
    real = shutil.which("flock")
    assert real is not None
    target = fake.root / "bin/flock"
    if target.is_symlink() or target.is_file():
        target.unlink()
    marker_value = fake.root / "flock-value"
    if value is None:
        if marker_value.is_file():
            marker_value.unlink()
    else:
        marker_value.write_bytes(value.encode())
    target.write_text(
        "#!/bin/bash\n"
        f'REAL="{real}"\n'
        f'VALFILE="{marker_value}"\n'
        'if [ -f "$VALFILE" ]; then\n'
        '  mkdir -p "$HOME/.local/share/naga-control"\n'
        '  cat "$VALFILE" > "$HOME/.local/share/naga-control/service-manager"\n'
        '  chmod 600 "$HOME/.local/share/naga-control/service-manager"\n'
        "fi\n"
        'exec "$REAL" "$@"\n'
    )
    target.chmod(0o755)
    return target


def test_install_session_to_systemd_aborts_without_mutations(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    previous = _seed_session(fake, active=False)
    _wrap_flock_set_mode(fake, "systemd\n")
    result, commands = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode != 0
    assert "changed while waiting" in result.stderr
    assert "rerun" in result.stderr.lower()
    assert mutations(commands) == []
    assert installed_image(fake).read_bytes() == previous
    assert (fake.root / "home/.local/share/naga-control/service-manager").read_text() == "systemd\n"
    assert_private_cleanup(fake)


def test_install_systemd_to_session_aborts_without_mutations(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    seed_previous(fake, active=False)
    (fake.root / "home/.local/share/naga-control/service-manager").write_text("systemd\n")
    _wrap_flock_set_mode(fake, "session\n")
    result, commands = fake.run("--version", TAG, "--service-manager", "systemd", script=script)
    assert result.returncode != 0
    assert "changed while waiting" in result.stderr
    assert mutations(commands) == []
    assert (fake.root / "home/.local/share/naga-control/service-manager").read_text() == "session\n"
    assert_private_cleanup(fake)


def test_install_fresh_to_session_aborts_without_mutations(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    fake.configure(bus_available=True, has_owner=False)
    _wrap_flock_set_mode(fake, "session\n")
    result, commands = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode != 0
    assert "changed while waiting" in result.stderr
    assert "fresh" in result.stderr
    assert mutations(commands) == []
    assert not installed_image(fake).exists()
    assert (fake.root / "home/.local/share/naga-control/service-manager").read_text() == "session\n"
    assert_private_cleanup(fake)


def test_install_no_change_happy_path(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    _seed_session(fake, active=False)
    _wrap_flock_set_mode(fake, None)
    result, _ = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode == 0, result.stderr
    assert (fake.root / "home/.local/share/naga-control/service-manager").read_text() == "session\n"
    assert_private_cleanup(fake)


def test_uninstall_session_to_systemd_aborts_without_deletions(tmp_path: Path) -> None:
    from tests.session_uninstaller_fakes import MODE, session_harness

    fake = session_harness(tmp_path)
    contents = fake.seed_session(has_owner=False)
    real = shutil.which("flock")
    assert real is not None
    target = fake.root / "bin/flock"
    if target.is_symlink() or target.is_file():
        target.unlink()
    valfile = fake.root / "flock-value"
    valfile.write_text("systemd\n")
    target.write_text(
        "#!/bin/bash\n"
        f'REAL="{real}"\n'
        f'VALFILE="{valfile}"\n'
        'mkdir -p "$HOME/.local/share/naga-control"\n'
        'cat "$VALFILE" > "$HOME/.local/share/naga-control/service-manager"\n'
        'chmod 600 "$HOME/.local/share/naga-control/service-manager"\n'
        'exec "$REAL" "$@"\n'
    )
    target.chmod(0o755)
    result, commands = fake.run("--yes")
    assert result.returncode != 0
    assert "changed while waiting" in result.stderr
    assert "rerun" in result.stderr.lower()
    assert not any(cmd[0] in {"rm", "rmdir", "sudo", "mv"} for cmd in commands)
    assert fake.dbus_calls() == []
    assert (fake.home / MODE).read_text() == "systemd\n"
    for relative, data in contents.items():
        if relative == MODE:
            continue
        assert (fake.home / relative).read_bytes() == data


def test_uninstall_systemd_to_session_aborts_without_deletions(tmp_path: Path) -> None:
    from tests.uninstaller_fakes import harness as legacy_harness

    fake = legacy_harness(tmp_path)
    contents = fake.seed()
    mode = fake.home / ".local/share/naga-control/service-manager"
    mode.parent.mkdir(parents=True, exist_ok=True)
    mode.write_text("systemd\n")
    mode.chmod(0o600)
    real = shutil.which("flock")
    assert real is not None
    target = fake.root / "bin/flock"
    if target.is_symlink() or target.is_file():
        target.unlink()
    valfile = fake.root / "flock-value"
    valfile.write_text("session\n")
    target.write_text(
        "#!/bin/bash\n"
        f'REAL="{real}"\n'
        f'VALFILE="{valfile}"\n'
        'cat "$VALFILE" > "$HOME/.local/share/naga-control/service-manager"\n'
        'chmod 600 "$HOME/.local/share/naga-control/service-manager"\n'
        'exec "$REAL" "$@"\n'
    )
    target.chmod(0o755)
    result, commands = fake.run("--yes")
    assert result.returncode != 0
    assert "changed while waiting" in result.stderr
    assert not any(cmd[0] in {"rm", "rmdir", "sudo"} for cmd in commands)
    assert mode.read_text() == "session\n"
    for relative, data in contents.items():
        assert (fake.home / relative).read_bytes() == data


def test_systemd_ignores_dot_xdg_config(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    fake.environment["XDG_CONFIG_HOME"] = "/tmp/../external-config"
    fake.configure(bus_available=True, has_owner=False)
    result, _ = fake.run("--version", TAG, "--service-manager", "systemd", script=script)
    assert result.returncode == 0, result.stderr
    assert (fake.root / "home/.local/share/naga-control/service-manager").read_text() == "systemd\n"
    assert not Path("/external-config").exists()
    assert_private_cleanup(fake)
