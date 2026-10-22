"""Installer XDG isolation: inherited host XDG must not leak into fakes."""

from pathlib import Path

import pytest

from tests.installer_app_fakes import (
    app_harness,
    assert_private_cleanup,
    installed_image,
    mutations,
)
from tests.openrazer_installer_fakes import TAG, InstallerHarness

MARKER = ".local/share/naga-control/service-manager"
HELPER = ".local/share/naga-control/session-service.sh"


def _autostart(fake: InstallerHarness) -> Path:
    return fake.root / "home/.config/autostart/org.nagacontrol.Service.desktop"


def test_inherited_outside_xdg_isolated_for_fresh_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "host-config"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("host\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(outside))
    fake, script = app_harness(tmp_path)
    assert fake.environment["XDG_CONFIG_HOME"] == str(fake.root / "home/.config")
    fake.configure(bus_available=True, has_owner=False)
    result, _ = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode == 0, result.stderr
    assert (fake.root / "home" / MARKER).read_text() == "session\n"
    assert (fake.root / "home" / HELPER).is_file()
    assert _autostart(fake).is_file()
    assert sentinel.read_text() == "host\n"
    assert not (outside / "autostart").exists()
    assert_private_cleanup(fake)


def test_explicit_outside_xdg_still_rejected_for_session(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    assert fake.environment["XDG_CONFIG_HOME"] == str(fake.root / "home/.config")
    external = tmp_path / "external-config"
    fake.environment["XDG_CONFIG_HOME"] = str(external)
    fake.configure(bus_available=True, has_owner=False)
    result, commands = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode != 0
    assert "outside HOME" in result.stderr or "XDG_CONFIG_HOME" in result.stderr
    assert mutations(commands) == []
    assert not installed_image(fake).exists()
    assert not external.exists()
    assert_private_cleanup(fake)


def test_inherited_outside_xdg_preserves_systemd_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "host-config"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("host\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(outside))
    fake, script = app_harness(tmp_path)
    assert fake.environment["XDG_CONFIG_HOME"] == str(fake.root / "home/.config")
    result, _ = fake.run("--version", TAG, "--service-manager", "systemd", script=script)
    assert result.returncode == 0, result.stderr
    assert (fake.root / "home" / MARKER).read_text() == "systemd\n"
    assert sentinel.read_text() == "host\n"
    assert not (outside / "autostart").exists()
    assert_private_cleanup(fake)


def test_relative_xdg_falls_back_to_private_home(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    fake.environment["XDG_CONFIG_HOME"] = "relative/path"
    fake.configure(bus_available=True, has_owner=False)
    result, _ = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode == 0, result.stderr
    assert (fake.root / "home" / MARKER).read_text() == "session\n"
    assert _autostart(fake).is_file()
    assert_private_cleanup(fake)
