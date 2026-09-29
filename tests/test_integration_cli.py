from pathlib import Path

import pytest

from naga_control.integration_cli import (
    IntegrationError,
    install,
    remove,
    status,
)


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "packaging"
    (source / "systemd/user").mkdir(parents=True)
    (source / "dbus-1/services").mkdir(parents=True)
    (source / "appimage").mkdir(parents=True)
    (source / "udev").mkdir(parents=True)
    (source / "systemd/user/naga-control.service").write_text(
        "[Service]\nExecStart=/usr/bin/env naga-control-service\n"
    )
    (source / "dbus-1/services/org.nagacontrol.Service1.service").write_text(
        "[D-BUS Service]\nExec=/usr/bin/env naga-control-service\n"
    )
    (source / "appimage/org.nagacontrol.NagaControl.desktop").write_text(
        "[Desktop Entry]\nExec=naga-control-gui\n"
    )
    (source / "udev/70-naga-control.rules").write_text('ACTION=="add", TAG+="uaccess"\n')
    for size in (64, 128, 256, 512):
        icon = source / f"appimage/icons/hicolor/{size}x{size}/apps"
        icon.mkdir(parents=True)
        (icon / "org.nagacontrol.NagaControl.png").write_bytes(b"\x89PNG")
    return source


def _dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    return _source(tmp_path), tmp_path / "home", tmp_path / "udev"


def test_install_writes_user_files_and_udev_rule(tmp_path: Path) -> None:
    source, home, udev = _dirs(tmp_path)

    installed = install(source, home=home, udev_dir=udev)

    assert (home / ".config/systemd/user/naga-control.service").is_file()
    assert (home / ".local/share/dbus-1/services/org.nagacontrol.Service1.service").is_file()
    assert (home / ".local/share/applications/org.nagacontrol.NagaControl.desktop").is_file()
    assert (udev / "70-naga-control.rules").is_file()
    assert len(installed) == 8


def test_install_rewrites_exec_lines_for_the_appimage(tmp_path: Path) -> None:
    source, home, udev = _dirs(tmp_path)

    install(source, home=home, udev_dir=udev, exec_prefix=Path("/opt/Naga.Control.AppImage"))

    unit = (home / ".config/systemd/user/naga-control.service").read_text()
    service = (home / ".local/share/dbus-1/services/org.nagacontrol.Service1.service").read_text()
    desktop = (home / ".local/share/applications/org.nagacontrol.NagaControl.desktop").read_text()
    assert "ExecStart=/opt/Naga.Control.AppImage service" in unit
    assert "Exec=/opt/Naga.Control.AppImage service" in service
    assert "Exec=/opt/Naga.Control.AppImage gui" in desktop


def test_install_without_exec_prefix_keeps_source_content(tmp_path: Path) -> None:
    source, home, udev = _dirs(tmp_path)

    install(source, home=home, udev_dir=udev)

    unit = (home / ".config/systemd/user/naga-control.service").read_text()
    assert "ExecStart=/usr/bin/env naga-control-service" in unit


def test_install_fails_on_missing_sources(tmp_path: Path) -> None:
    with pytest.raises(IntegrationError):
        install(tmp_path / "nowhere", home=tmp_path / "home", udev_dir=tmp_path / "udev")


def test_remove_and_status_round_trip(tmp_path: Path) -> None:
    source, home, udev = _dirs(tmp_path)
    install(source, home=home, udev_dir=udev)

    assert all(present for _name, present in status(home=home, udev_dir=udev))

    removed = remove(home=home, udev_dir=udev)

    assert len(removed) == 8
    assert not any(present for _name, present in status(home=home, udev_dir=udev))


def test_status_without_udev_dir_skips_the_rule(tmp_path: Path) -> None:
    source, home, _udev = _dirs(tmp_path)
    install(source, home=home, udev_dir=None)

    report = dict(status(home=home, udev_dir=None))

    assert report["systemd user unit"] is True
    assert report["D-Bus session service"] is True
    assert report["desktop entry"] is True
    assert report["udev rule"] is False


def test_install_places_hicolor_icons(tmp_path: Path) -> None:
    source, home, udev = _dirs(tmp_path)

    installed = install(source, home=home, udev_dir=udev)

    for size in (64, 128, 256, 512):
        target = (
            home / f".local/share/icons/hicolor/{size}x{size}/apps/org.nagacontrol.NagaControl.png"
        )
        assert target.is_file(), size
    assert any("icons" in path for path in installed)
