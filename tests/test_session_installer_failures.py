"""Session failure and fence ordering (fake only, no live bus)."""

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


def _autostart(fake: InstallerHarness) -> Path:
    return fake.root / "home/.config/autostart/org.nagacontrol.Service.desktop"


def _seed_session(fake: InstallerHarness, *, active: bool = True, tag: str = "v0.3.0") -> bytes:
    old: bytes = fake.remote.joinpath(ASSET).read_bytes()
    image = installed_image(fake)
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
    autostart = _autostart(fake)
    autostart.parent.mkdir(parents=True, exist_ok=True)
    autostart.write_text(
        "[Desktop Entry]\nType=Application\nName=Naga Control background service\nExec="
        + str(image)
        + " service\nHidden=false\nX-NagaControl-Service=true\n"
    )
    for relative in (
        ".local/bin/naga-control",
        ".local/share/applications/org.nagacontrol.NagaControl.desktop",
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


def _dbus_methods(commands: list[list[str]]) -> list[str]:
    methods: list[str] = []
    for args in commands:
        if args[0] != "dbus-send":
            continue
        for arg in args:
            if arg.startswith("org.freedesktop.DBus.") or arg.startswith(
                "org.nagacontrol.Service1."
            ):
                methods.append(arg)
                break
    return methods


def test_no_usable_manager_has_no_mutations(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    fake.configure(systemd_failure=1, bus_failure=1, bus_available=False)
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode != 0
    assert "no usable service manager" in result.stderr
    assert mutations(commands) == []
    assert not installed_image(fake).exists()
    assert not (fake.root / "home/.local").exists()
    assert_private_cleanup(fake)


@pytest.mark.parametrize(
    "content",
    ["bogus\n", "session\nsecond\n", "session", "SYSTEMD\n", "session\r\n"],
)
def test_malformed_marker_blocked(tmp_path: Path, content: str) -> None:
    fake, script = app_harness(tmp_path)
    _seed_session(fake, active=False)
    (fake.root / "home" / MARKER).write_bytes(content.encode())
    result, commands = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode != 0
    assert "misconfigured" in result.stderr
    assert mutations(commands) == []
    assert_private_cleanup(fake)


def test_explicit_mode_mismatch_refused(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    _seed_session(fake, active=False)
    result, commands = fake.run("--version", TAG, "--service-manager", "systemd", script=script)
    assert result.returncode != 0
    assert "mismatch" in result.stderr and "manual migration" in result.stderr
    assert mutations(commands) == []
    assert_private_cleanup(fake)


def test_legacy_systemd_mismatch_refused(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    seed_previous(fake)
    result, commands = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode != 0
    assert "mismatch" in result.stderr
    assert mutations(commands) == []
    assert_private_cleanup(fake)


@pytest.mark.parametrize("kind", ["symlink", "foreign"])
def test_autostart_path_or_foreign_blocked(tmp_path: Path, kind: str) -> None:
    fake, script = app_harness(tmp_path)
    fake.configure(bus_available=True, has_owner=False)
    target = _autostart(fake)
    target.parent.mkdir(parents=True, exist_ok=True)
    if kind == "symlink":
        outside = fake.root / "outside"
        outside.write_text("keep\n")
        target.symlink_to(outside)
    else:
        target.write_text("[Desktop Entry]\nType=Application\nName=Other\nExec=/bin/true\n")
    result, commands = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode != 0
    assert "symlink" in result.stderr or "foreign" in result.stderr
    assert mutations(commands) == []
    assert_private_cleanup(fake)


def test_explicit_openrazer_optin_fails_early(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    fake.configure(bus_available=True, has_owner=False)
    result, commands = fake.run(
        "--version",
        TAG,
        "--service-manager",
        "session",
        "--install-openrazer",
        script=script,
    )
    assert result.returncode != 0
    assert "manual" in result.stderr
    assert mutations(commands) == []
    assert not any(c[0] == "curl" for c in commands)
    assert not installed_image(fake).exists()
    assert_private_cleanup(fake)


def test_old_image_rejected_before_stop(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    previous = _seed_session(fake, active=True)
    fake.configure(session_unsupported=True)
    result, commands = fake.run(
        "--version",
        TAG,
        "--service-manager",
        "session",
        "--restart-service",
        script=script,
    )
    assert result.returncode != 0
    assert (
        "lacks --service-manager" in result.stderr or "session integration failed" in result.stderr
    )
    assert installed_image(fake).read_bytes() == previous
    assert "SystemdService=" not in (fake.root / "home" / ACTIVATION).read_text()
    assert "PrepareShutdown" not in str(commands)
    assert_private_cleanup(fake)


def test_prepare_failure_keeps_fence_without_replace(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    previous = _seed_session(fake, active=True)
    fake.configure(prepare_fail=True)
    result, _ = fake.run(
        "--version",
        TAG,
        "--service-manager",
        "session",
        "--restart-service",
        script=script,
    )
    assert result.returncode != 0
    assert "stop failed" in result.stderr or "fenced" in result.stderr
    assert installed_image(fake).read_bytes() == previous
    assert "Exec=/bin/false" in (fake.root / "home" / ACTIVATION).read_text()
    assert_private_cleanup(fake)


def test_blocker_reload_before_prepare(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    _seed_session(fake, active=True)
    result, commands = fake.run(
        "--version",
        TAG,
        "--service-manager",
        "session",
        "--restart-service",
        script=script,
    )
    assert result.returncode == 0, result.stderr
    methods = _dbus_methods(commands)
    assert "org.freedesktop.DBus.ReloadConfig" in methods
    assert "org.nagacontrol.Service1.PrepareShutdown" in methods
    assert methods.index("org.freedesktop.DBus.ReloadConfig") < methods.index(
        "org.nagacontrol.Service1.PrepareShutdown"
    )
    prepare = methods.index("org.nagacontrol.Service1.PrepareShutdown")
    exit_m = methods.index("org.nagacontrol.Service1.Exit")
    assert prepare < exit_m
    assert_private_cleanup(fake)


def test_stop_timeout_never_replaces_image(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    previous = _seed_session(fake, active=True)
    fake.configure(after_unique_owner=True, after_well_owner=True)
    result, _ = fake.run(
        "--version",
        TAG,
        "--service-manager",
        "session",
        "--restart-service",
        script=script,
    )
    assert result.returncode != 0
    assert installed_image(fake).read_bytes() == previous
    assert_private_cleanup(fake)


def test_unverified_previous_has_no_auto_resume(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    _seed_session(fake, active=False)
    installed_image(fake).write_bytes(b"tampered-local\n")
    result, _ = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode == 0, result.stderr
    assert "removed unverified quarantine" in result.stdout
    assert_private_cleanup(fake)
