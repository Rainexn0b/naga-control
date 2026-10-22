"""Fake-only per-user session integration: autostart instead of a user unit."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from buildpython.steps.appimage.assets import SYSTEM_TEMPLATES, copy_assets
from buildpython.steps.step_repo_validation import REQUIRED_FILES
from buildpython.steps.step_shellcheck import shell_scripts
from naga_control.integration_cli import (
    INTEGRATION_FILES,
    SESSION_AUTOSTART,
    IntegrationError,
    ServiceManager,
    install,
    main,
    remove,
    status,
)

ROOT = Path(__file__).resolve().parents[1]
IMAGE = Path("/opt/Naga.Control.AppImage")


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


def _unit(home: Path) -> Path:
    return home / ".config/systemd/user/naga-control.service"


def _dbus(home: Path) -> Path:
    return home / ".local/share/dbus-1/services/org.nagacontrol.Service1.service"


def _autostart(home: Path) -> Path:
    return home / ".config/autostart/org.nagacontrol.Service.desktop"


def _gui_entry(home: Path) -> Path:
    return home / ".local/share/applications/org.nagacontrol.NagaControl.desktop"


def test_default_manifest_stays_eight_and_excludes_session_autostart() -> None:
    assert len(INTEGRATION_FILES) == 8
    assert SESSION_AUTOSTART not in INTEGRATION_FILES
    assert SESSION_AUTOSTART.relative_source == "autostart/org.nagacontrol.Service.desktop"
    assert SESSION_AUTOSTART.rewrite_command == "service"


def test_systemd_default_install_is_unchanged(tmp_path: Path) -> None:
    source = _source(tmp_path / "payload")
    home, udev = tmp_path / "home", tmp_path / "udev"

    installed = install(source, home=home, udev_dir=udev)

    assert len(installed) == 8
    assert _unit(home).is_file()
    assert not _autostart(home).is_file()
    direct = _dbus(home).read_text()
    assert "SystemdService=naga-control.service\n" in direct
    assert "Exec=/usr/bin/env naga-control-service\n" in direct


def test_session_install_swaps_unit_for_owned_autostart(tmp_path: Path) -> None:
    source = _source(tmp_path / "payload")
    home, udev = tmp_path / "home", tmp_path / "udev"

    installed = install(source, home=home, udev_dir=udev, service_manager="session")

    assert len(installed) == 8
    assert not _unit(home).exists()
    entry = _autostart(home).read_text()
    assert "Type=Application\n" in entry
    assert "Name=Naga Control background service\n" in entry
    assert "Exec=/usr/bin/env naga-control-service\n" in entry
    assert "Hidden=false\n" in entry
    assert "X-NagaControl-Service=true\n" in entry
    direct = _dbus(home).read_text()
    assert "Name=org.nagacontrol.Service1\n" in direct
    assert "Exec=/usr/bin/env naga-control-service\n" in direct
    assert "SystemdService=" not in direct
    gui = _gui_entry(home).read_text()
    assert "Exec=naga-control-gui\n" in gui
    assert "X-NagaControl-Service" not in gui


def test_session_install_renders_appimage_exec(tmp_path: Path) -> None:
    source = _source(tmp_path / "payload")
    home, udev = tmp_path / "home", tmp_path / "udev"

    installed = install(
        source, home=home, udev_dir=udev, exec_prefix=IMAGE, service_manager="session"
    )

    assert len(installed) == 8
    assert f"Exec={IMAGE} service\n" in _autostart(home).read_text()
    rendered = _dbus(home).read_text()
    assert f"Exec={IMAGE} service\n" in rendered
    assert "SystemdService=" not in rendered
    assert "/usr/bin/env naga-control-service" not in rendered


def test_remove_and_status_select_mode(tmp_path: Path) -> None:
    source = _source(tmp_path / "payload")
    home, udev = tmp_path / "home", tmp_path / "udev"
    install(source, home=home, udev_dir=udev, service_manager="session")

    session_report = dict(status(home=home, udev_dir=udev, service_manager="session"))

    assert len(session_report) == 8
    assert session_report["session autostart entry"] is True
    assert "systemd user unit" not in session_report
    assert all(session_report.values())
    systemd_report = dict(status(home=home, udev_dir=udev))
    assert systemd_report["systemd user unit"] is False
    assert systemd_report["D-Bus session service"] is True

    removed = remove(home=home, udev_dir=udev, service_manager="session")

    assert len(removed) == 8
    assert not any(
        present for _name, present in status(home=home, udev_dir=udev, service_manager="session")
    )
    assert not _unit(home).exists()


def test_systemd_remove_round_trip_still_exact8(tmp_path: Path) -> None:
    source = _source(tmp_path / "payload")
    home, udev = tmp_path / "home", tmp_path / "udev"
    install(source, home=home, udev_dir=udev)

    removed = remove(home=home, udev_dir=udev)

    assert len(removed) == 8
    assert not any(present for _name, present in status(home=home, udev_dir=udev))


def test_custom_config_home_selects_autostart_target(tmp_path: Path) -> None:
    source = _source(tmp_path / "payload")
    home, udev = tmp_path / "home", tmp_path / "udev"
    custom = tmp_path / "custom-config"
    expected = custom / "autostart/org.nagacontrol.Service.desktop"

    installed = install(
        source, home=home, udev_dir=udev, service_manager="session", config_home=custom
    )

    assert len(installed) == 8
    assert expected.is_file()
    assert not _autostart(home).exists()
    assert (
        dict(status(home=home, udev_dir=udev, service_manager="session"))["session autostart entry"]
        is False
    )
    assert (
        dict(status(home=home, udev_dir=udev, service_manager="session", config_home=custom))[
            "session autostart entry"
        ]
        is True
    )

    assert len(remove(home=home, udev_dir=udev, service_manager="session")) == 7
    assert expected.is_file()
    assert len(remove(home=home, udev_dir=udev, service_manager="session", config_home=custom)) == 1
    assert not expected.exists()


def test_default_session_staging_ignores_real_xdg_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path / "payload")
    home = tmp_path / "home"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "real-xdg"))

    install(source, home=home, udev_dir=None, service_manager="session")

    assert _autostart(home).is_file()
    assert not (tmp_path / "real-xdg").exists()


def test_cli_explicit_home_ignores_inherited_xdg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path / "payload")
    home, udev = tmp_path / "home", tmp_path / "udev"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "real-xdg"))

    assert (
        main(
            [
                "install",
                "--source-dir",
                str(source),
                "--home",
                str(home),
                "--udev-dir",
                str(udev),
                "--service-manager",
                "session",
            ]
        )
        == 0
    )

    assert _autostart(home).is_file()
    assert not (tmp_path / "real-xdg").exists()


def test_cli_uses_absolute_xdg_without_explicit_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path / "payload")
    fake_home, udev = tmp_path / "fake-home", tmp_path / "udev"
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-home"))

    assert (
        main(
            [
                "install",
                "--source-dir",
                str(source),
                "--udev-dir",
                str(udev),
                "--service-manager",
                "session",
            ]
        )
        == 0
    )

    staged = tmp_path / "xdg-home/autostart/org.nagacontrol.Service.desktop"
    assert staged.is_file()
    assert not _autostart(fake_home).exists()


def test_cli_relative_xdg_falls_back_to_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path / "payload")
    fake_home, udev = tmp_path / "fake-home", tmp_path / "udev"
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/path")

    assert (
        main(
            [
                "install",
                "--source-dir",
                str(source),
                "--udev-dir",
                str(udev),
                "--service-manager",
                "session",
            ]
        )
        == 0
    )

    assert _autostart(fake_home).is_file()


def test_cli_config_home_override_wins(tmp_path: Path) -> None:
    source = _source(tmp_path / "payload")
    home, udev = tmp_path / "home", tmp_path / "udev"
    custom = tmp_path / "staged-config"

    assert (
        main(
            [
                "install",
                "--source-dir",
                str(source),
                "--home",
                str(home),
                "--udev-dir",
                str(udev),
                "--service-manager",
                "session",
                "--config-home",
                str(custom),
            ]
        )
        == 0
    )

    assert (custom / "autostart/org.nagacontrol.Service.desktop").is_file()
    assert not _autostart(home).exists()


def test_cli_rejects_unknown_service_manager(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["install", "--home", str(tmp_path), "--service-manager", "bogus"])
    assert exc.value.code == 2


def test_python_api_rejects_invalid_service_manager(tmp_path: Path) -> None:
    source = _source(tmp_path / "payload")
    home = tmp_path / "home"
    bogus = cast(ServiceManager, "upstart")

    with pytest.raises(IntegrationError):
        install(source, home=home, service_manager=bogus)
    with pytest.raises(IntegrationError):
        remove(home=home, service_manager=bogus)
    with pytest.raises(IntegrationError):
        status(home=home, service_manager=bogus)


def test_validators_include_session_payload() -> None:
    assert SYSTEM_TEMPLATES.count("autostart/org.nagacontrol.Service.desktop") == 1
    assert REQUIRED_FILES.count("system/autostart/org.nagacontrol.Service.desktop") == 1
    assert REQUIRED_FILES.count("scripts/session_service.sh") == 1
    assert shell_scripts().count("scripts/session_service.sh") == 1


def test_real_source_and_appdir_session_install_match(tmp_path: Path) -> None:
    appdir = tmp_path / "AppDir"
    bundled = copy_assets(root=ROOT, appdir=appdir)
    for label, source in (("checkout", ROOT / "system"), ("bundle", bundled)):
        home = tmp_path / label
        installed = install(
            source,
            home=home,
            udev_dir=tmp_path / f"{label}-udev",
            exec_prefix=IMAGE,
            service_manager="session",
        )
        assert len(installed) == 8
        assert not _unit(home).exists()
        assert f"Exec={IMAGE} service\n" in _autostart(home).read_text()
        rendered = _dbus(home).read_text()
        assert "SystemdService=" not in rendered
        assert f"Exec={IMAGE} service\n" in rendered
    checkout, bundle = tmp_path / "checkout", tmp_path / "bundle"
    for file in checkout.rglob("*"):
        if file.is_file():
            assert file.read_bytes() == (bundle / file.relative_to(checkout)).read_bytes()
