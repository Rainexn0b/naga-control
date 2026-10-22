"""Fake-only permission regression: install must not widen private config dirs."""

from __future__ import annotations

import stat
from pathlib import Path

from naga_control.integration_cli import install


def _source(root: Path) -> Path:
    source = root / "system"
    (source / "systemd/user").mkdir(parents=True)
    (source / "dbus-1/services").mkdir(parents=True)
    (source / "desktop").mkdir(parents=True)
    (source / "udev").mkdir(parents=True)
    (source / "autostart").mkdir(parents=True)
    (source / "systemd/user/naga-control.service").write_text(
        "[Service]\nExecStart=/usr/bin/env naga-control-service\nKillMode=mixed\n"
    )
    (source / "dbus-1/services/org.nagacontrol.Service1.service").write_text(
        "[D-BUS Service]\nName=org.nagacontrol.Service1\n"
        "SystemdService=naga-control.service\n"
        "Exec=/usr/bin/env naga-control-service\n"
    )
    (source / "desktop/org.nagacontrol.NagaControl.desktop").write_text(
        "[Desktop Entry]\nExec=naga-control-gui\n"
    )
    (source / "udev/70-naga-control.rules").write_text('ACTION=="add", TAG+="uaccess"\n')
    (source / "autostart/org.nagacontrol.Service.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Naga Control background service\n"
        "Exec=/usr/bin/env naga-control-service\nHidden=false\nX-NagaControl-Service=true\n"
    )
    for size in (64, 128, 256, 512):
        icon = root / f"assets/icons/hicolor/{size}x{size}/apps"
        icon.mkdir(parents=True)
        (icon / "org.nagacontrol.NagaControl.png").write_bytes(b"\x89PNG")
    return source


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_private_config_home_parents_stay_private(tmp_path: Path) -> None:
    source = _source(tmp_path / "payload")
    home, udev = tmp_path / "home", tmp_path / "udev"
    custom = tmp_path / "private-config"
    custom.mkdir(mode=0o700)
    (custom / "autostart").mkdir(mode=0o700)

    installed = install(
        source, home=home, udev_dir=udev, service_manager="session", config_home=custom
    )

    assert len(installed) == 8
    entry = custom / "autostart/org.nagacontrol.Service.desktop"
    assert entry.is_file()
    assert _mode(custom) == 0o700
    assert _mode(custom / "autostart") == 0o700
    assert _mode(entry) == 0o644


def test_default_home_config_parents_stay_private(tmp_path: Path) -> None:
    source = _source(tmp_path / "payload")
    home, udev = tmp_path / "home", tmp_path / "udev"
    home.mkdir(mode=0o700)
    (home / ".config").mkdir(mode=0o700)
    (home / ".config/autostart").mkdir(mode=0o700)

    installed = install(source, home=home, udev_dir=udev, service_manager="session")

    assert len(installed) == 8
    assert _mode(home) == 0o700
    assert _mode(home / ".config") == 0o700
    assert _mode(home / ".config/autostart") == 0o700


def test_systemd_unit_parents_stay_private(tmp_path: Path) -> None:
    source = _source(tmp_path / "payload")
    home, udev = tmp_path / "home", tmp_path / "udev"
    home.mkdir(mode=0o700)
    (home / ".config").mkdir(mode=0o700)

    installed = install(source, home=home, udev_dir=udev)

    assert len(installed) == 8
    assert _mode(home) == 0o700
    assert _mode(home / ".config") == 0o700


def test_icon_theme_dirs_stay_world_readable(tmp_path: Path) -> None:
    source = _source(tmp_path / "payload")
    home, udev = tmp_path / "home", tmp_path / "udev"
    apps = home / ".local/share/icons/hicolor/64x64/apps"
    apps.mkdir(parents=True, mode=0o700)

    installed = install(source, home=home, udev_dir=udev, service_manager="session")

    assert len(installed) == 8
    icon = apps / "org.nagacontrol.NagaControl.png"
    assert icon.is_file()
    assert _mode(apps) == 0o755
    assert _mode(apps.parent) == 0o755
