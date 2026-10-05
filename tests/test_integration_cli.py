from pathlib import Path

import pytest

from naga_control import integration_cli
from naga_control.integration_cli import (
    IntegrationError,
    default_source_dir,
    install,
    main,
    remove,
    status,
)


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "system"
    (source / "systemd/user").mkdir(parents=True)
    (source / "dbus-1/services").mkdir(parents=True)
    (source / "desktop").mkdir(parents=True)
    (source / "udev").mkdir(parents=True)
    (source / "systemd/user/naga-control.service").write_text(
        "[Service]\nExecStart=/usr/bin/env naga-control-service\nKillMode=mixed\n"
    )
    (source / "dbus-1/services/org.nagacontrol.Service1.service").write_text(
        "[D-BUS Service]\nExec=/usr/bin/env naga-control-service\n"
    )
    (source / "desktop/org.nagacontrol.NagaControl.desktop").write_text(
        "[Desktop Entry]\nExec=naga-control-gui\n"
    )
    (source / "udev/70-naga-control.rules").write_text('ACTION=="add", TAG+="uaccess"\n')
    for size in (64, 128, 256, 512):
        icon = tmp_path / f"assets/icons/hicolor/{size}x{size}/apps"
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


def test_packaged_unit_preserves_appimage_shutdown_order(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "system"
    home = tmp_path / "home"
    install(source, home=home, exec_prefix=Path("/opt/Naga.Control.AppImage"))

    unit = (home / ".config/systemd/user/naga-control.service").read_text()
    assert "ExecStart=/opt/Naga.Control.AppImage service\n" in unit
    assert "KillMode=mixed\n" in unit


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


@pytest.mark.parametrize("bundled", [False, True], ids=["checkout", "AppDir"])
def test_default_source_discovery_and_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bundled: bool
) -> None:
    root = tmp_path / "checkout"
    if bundled:
        appdir = tmp_path / "AppDir"
        monkeypatch.setenv("APPDIR", str(appdir))
        root = appdir / "usr/share/naga-control"
    else:
        monkeypatch.delenv("APPDIR", raising=False)
        monkeypatch.setattr(
            integration_cli, "__file__", str(root / "src/naga_control/integration_cli.py")
        )
    source = _source(root)
    home, udev = tmp_path / "home", tmp_path / "safe-udev"
    executable = tmp_path / "Naga-Control.AppImage"

    assert default_source_dir() == source
    assert (
        main(
            [
                "install",
                "--home",
                str(home),
                "--udev-dir",
                str(udev),
                "--exec-prefix",
                str(executable),
            ]
        )
        == 0
    )

    expected = {
        ".config/systemd/user/naga-control.service",
        ".local/share/dbus-1/services/org.nagacontrol.Service1.service",
        ".local/share/applications/org.nagacontrol.NagaControl.desktop",
        *(
            f".local/share/icons/hicolor/{size}x{size}/apps/org.nagacontrol.NagaControl.png"
            for size in (64, 128, 256, 512)
        ),
    }
    assert {str(path.relative_to(home)) for path in home.rglob("*") if path.is_file()} == expected
    assert (udev / "70-naga-control.rules").read_bytes() == (
        source / "udev/70-naga-control.rules"
    ).read_bytes()
    assert all(present for _, present in status(home=home, udev_dir=udev))
    unit = (home / ".config/systemd/user/naga-control.service").read_text()
    assert f"ExecStart={executable} service\n" in unit
    assert "KillMode=mixed\n" in unit


def test_explicit_source_override_uses_system_and_sibling_assets(tmp_path: Path) -> None:
    source = _source(tmp_path / "custom-payload")
    home, udev = tmp_path / "home", tmp_path / "safe-udev"

    assert (
        main(["install", "--source-dir", str(source), "--home", str(home), "--udev-dir", str(udev)])
        == 0
    )
    assert len(status(home=home, udev_dir=udev)) == 8
    assert all(present for _, present in status(home=home, udev_dir=udev))
