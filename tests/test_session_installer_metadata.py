"""Session preflight metadata: marker, address, ownership guards."""

import hashlib
from pathlib import Path

import pytest

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
SENTINEL = ".local/share/naga-control/service-manager.canonical-check"


def _autostart(fake: InstallerHarness) -> Path:
    return fake.root / "home/.config/autostart/org.nagacontrol.Service.desktop"


def _seed_session(fake: InstallerHarness, *, active: bool = False) -> bytes:
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


def _dbus_calls(commands: list[list[str]]) -> list[list[str]]:
    return [c for c in commands if c[0] == "dbus-send"]


def test_no_canonical_check_sentinel_clobber(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    sentinel: Path = fake.root / "home" / SENTINEL
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("operator sentinel\n")
    fake.configure(bus_available=True, has_owner=False)
    result, _ = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode == 0, result.stderr
    assert sentinel.read_text() == "operator sentinel\n"
    assert_private_cleanup(fake)


def test_canonical_check_symlink_not_followed(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    sentinel: Path = fake.root / "home" / SENTINEL
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    outside: Path = fake.root / "outside-sentinel"
    outside.write_text("keep\n")
    sentinel.symlink_to(outside)
    fake.configure(bus_available=True, has_owner=False)
    result, _ = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode == 0, result.stderr
    assert outside.read_text() == "keep\n"
    assert sentinel.is_symlink()
    assert_private_cleanup(fake)


@pytest.mark.parametrize(
    "payload",
    [b"session\x00\n", b"a" * 100 + b"\n", b"session\nsecond\n"],
)
def test_invalid_marker_nul_large_extra_no_mutations(tmp_path: Path, payload: bytes) -> None:
    fake, script = app_harness(tmp_path)
    _seed_session(fake)
    (fake.root / "home" / MARKER).write_bytes(payload)
    result, commands = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode != 0
    assert "misconfigured" in result.stderr
    assert mutations(commands) == []
    assert_private_cleanup(fake)


def test_symlink_marker_no_mutations(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    _seed_session(fake)
    marker: Path = fake.root / "home" / MARKER
    outside: Path = fake.root / "outside-marker"
    outside.write_text("session\n")
    marker.unlink()
    marker.symlink_to(outside)
    result, commands = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode != 0
    assert "misconfigured" in result.stderr or "symlink" in result.stderr
    assert mutations(commands) == []
    assert outside.read_text() == "session\n"
    assert_private_cleanup(fake)


@pytest.mark.parametrize("address", [None, "", "unix:abstract=/tmp/fake,autolaunch:1"])
def test_missing_autolaunch_address_zero_dbus(tmp_path: Path, address: str | None) -> None:
    fake, script = app_harness(tmp_path)
    if address is None:
        fake.environment.pop("DBUS_SESSION_BUS_ADDRESS", None)
    else:
        fake.environment["DBUS_SESSION_BUS_ADDRESS"] = address
    result, commands = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode != 0
    assert "session" in result.stderr.lower() or "bus" in result.stderr.lower()
    assert _dbus_calls(commands) == []
    assert not installed_image(fake).exists()
    assert_private_cleanup(fake)


def test_systemd_external_xdg_not_regressed(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    fake.environment["XDG_CONFIG_HOME"] = "/tmp/outside-config"
    result, _ = fake.run("--version", TAG, "--service-manager", "systemd", script=script)
    assert result.returncode == 0, result.stderr
    assert (fake.root / "home" / MARKER).read_text() == "systemd\n"
    assert_private_cleanup(fake)


def test_root_fails_without_queries(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    fake.configure(uid="0")
    result, commands = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode != 0
    assert "not root" in result.stderr
    assert _dbus_calls(commands) == []
    assert not any(c[0] == "curl" for c in commands)
    assert mutations(commands) == []
    assert_private_cleanup(fake)


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("prefix", "[D-BUS Service]\nName=org.nagacontrol.Service1.evil\nExec=/bin/false\n"),
        (
            "wrong_systemd",
            "[D-BUS Service]\nName=other.service\nSystemdService=naga-control.service\nExec=/bin/false\n",
        ),
        (
            "systemd_managed",
            "[D-BUS Service]\nName=org.nagacontrol.Service1\nSystemdService=naga-control.service\nExec=/bin/false\n",
        ),
    ],
)
def test_foreign_activation_rejected(tmp_path: Path, name: str, content: str) -> None:
    del name
    fake, script = app_harness(tmp_path)
    fake.configure(bus_available=True, has_owner=False)
    target: Path = fake.root / "home" / ACTIVATION
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    result, commands = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode != 0
    assert "foreign" in result.stderr
    assert mutations(commands) == []
    assert target.read_text() == content
    assert_private_cleanup(fake)


@pytest.mark.parametrize(
    ("name", "content"),
    [
        (
            "suffix",
            "[Desktop Entry]\nType=Application\nX-NagaControl-Service=true-evil\nExec=/bin/false\n",
        ),
        (
            "wrong_group",
            "[Desktop Entry]\nType=Application\nExec=/bin/false\n[Other]\nX-NagaControl-Service=true\n",
        ),
    ],
)
def test_foreign_autostart_rejected(tmp_path: Path, name: str, content: str) -> None:
    del name
    fake, script = app_harness(tmp_path)
    fake.configure(bus_available=True, has_owner=False)
    target: Path = _autostart(fake)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    result, commands = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode != 0
    assert "foreign" in result.stderr
    assert mutations(commands) == []
    assert target.read_text() == content
    assert_private_cleanup(fake)


def test_session_marker_with_unit_leftover_fails(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    _seed_session(fake)
    unit: Path = fake.root / "home/.config/systemd/user/naga-control.service"
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text("leftover unit\n")
    result, commands = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode != 0
    assert "unit" in result.stderr.lower() or "migration" in result.stderr.lower()
    assert mutations(commands) == []
    assert_private_cleanup(fake)


def test_legacy_systemd_preserved(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    seed_previous(fake)
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    assert (fake.root / "home" / MARKER).read_text() == "systemd\n"
    assert_private_cleanup(fake)


def test_canonical_check_hardlink_preserved(tmp_path: Path) -> None:
    import os

    fake, script = app_harness(tmp_path)
    sentinel: Path = fake.root / "home" / SENTINEL
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("operator sentinel\n")
    hardlink: Path = fake.root / "hardlink-sentinel"
    os.link(sentinel, hardlink)
    fake.configure(bus_available=True, has_owner=False)
    result, _ = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode == 0, result.stderr
    assert sentinel.read_text() == "operator sentinel\n"
    assert hardlink.read_text() == "operator sentinel\n"
    assert_private_cleanup(fake)


def test_session_external_xdg_rejected(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    fake.environment["XDG_CONFIG_HOME"] = "/tmp/outside-config"
    fake.configure(bus_available=True, has_owner=False)
    result, commands = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode != 0
    assert "outside HOME" in result.stderr or "XDG_CONFIG_HOME" in result.stderr
    assert mutations(commands) == []
    assert not installed_image(fake).exists()
    assert_private_cleanup(fake)
