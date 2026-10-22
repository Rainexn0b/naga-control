"""Real source assets assemble into an installable, hardware-independent payload."""

from pathlib import Path

import pytest

from buildpython.steps.appimage.assets import APP_ID, ICON_SIZES, copy_assets
from naga_control.integration_cli import default_source_dir, install

ROOT = Path(__file__).resolve().parents[1]


def test_real_appdir_payload_installs_without_build_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    appdir = tmp_path / "AppDir"
    source = copy_assets(root=ROOT, appdir=appdir)
    monkeypatch.setenv("APPDIR", str(appdir))
    assert default_source_dir() == source
    home = tmp_path / "home"
    image = tmp_path / "Naga-Control.AppImage"
    installed = install(source, home=home, udev_dir=tmp_path / "udev", exec_prefix=image)
    assert len(installed) == 8
    unit = (home / ".config/systemd/user/naga-control.service").read_text()
    assert "KillMode=mixed" in unit
    assert f"ExecStart={image} service" in unit
    assert (appdir / "AppRun").stat().st_mode & 0o111
    assert (appdir / "AppRun").read_bytes() == (
        ROOT / "buildpython/steps/appimage/AppRun"
    ).read_bytes()
    for size in ICON_SIZES:
        relative = f"hicolor/{size}x{size}/apps/{APP_ID}.png"
        expected = (ROOT / "assets/icons" / relative).read_bytes()
        assert (home / ".local/share/icons" / relative).read_bytes() == expected
        assert (appdir / "usr/share/icons" / relative).read_bytes() == expected
    assert not list(appdir.rglob("*.py"))
    assert not list(appdir.rglob("*.sh"))
    assert not (appdir / "usr/share/naga-control/packaging").exists()


def test_bundled_dbus_service_keeps_systemd_with_direct_exec_fallback(
    tmp_path: Path,
) -> None:
    appdir = tmp_path / "AppDir"
    source = copy_assets(root=ROOT, appdir=appdir)
    template = (source / "dbus-1/services/org.nagacontrol.Service1.service").read_text()
    assert "Name=org.nagacontrol.Service1\n" in template
    assert "SystemdService=naga-control.service\n" in template
    assert "Exec=/usr/bin/env naga-control-service\n" in template

    direct_home = tmp_path / "direct-home"
    install(source, home=direct_home, udev_dir=tmp_path / "direct-udev")
    direct = (
        direct_home / ".local/share/dbus-1/services/org.nagacontrol.Service1.service"
    ).read_text()
    assert "Name=org.nagacontrol.Service1\n" in direct
    assert "SystemdService=naga-control.service\n" in direct
    assert "Exec=/usr/bin/env naga-control-service\n" in direct

    rendered_home = tmp_path / "rendered-home"
    image = tmp_path / "Naga-Control.AppImage"
    install(
        source,
        home=rendered_home,
        udev_dir=tmp_path / "rendered-udev",
        exec_prefix=image,
    )
    rendered = (
        rendered_home / ".local/share/dbus-1/services/org.nagacontrol.Service1.service"
    ).read_text()
    assert "Name=org.nagacontrol.Service1\n" in rendered
    assert "SystemdService=naga-control.service\n" in rendered
    assert f"Exec={image} service\n" in rendered
    assert "/usr/bin/env naga-control-service" not in rendered


def test_checkout_and_bundled_integrations_have_identical_contents(tmp_path: Path) -> None:
    source = copy_assets(root=ROOT, appdir=tmp_path / "AppDir")
    for name, root in (("checkout", ROOT / "system"), ("bundle", source)):
        install(
            root,
            home=tmp_path / name,
            udev_dir=tmp_path / f"{name}-udev",
            exec_prefix=Path("/test/naga-control.AppImage"),
        )
    checkout = tmp_path / "checkout"
    bundle = tmp_path / "bundle"
    for file in checkout.rglob("*"):
        if file.is_file():
            assert file.read_bytes() == (bundle / file.relative_to(checkout)).read_bytes()
    assert (tmp_path / "checkout-udev/70-naga-control.rules").read_bytes() == (
        tmp_path / "bundle-udev/70-naga-control.rules"
    ).read_bytes()
