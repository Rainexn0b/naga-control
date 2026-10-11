"""Native recovery: commit, enable-only, and failure preservation."""

import os
import pty
from pathlib import Path

from tests.installer_app_fakes import (
    ASSET,
    assert_private_cleanup,
    installed_image,
    seed_altered_previous,
    seed_previous,
    stamp,
)
from tests.installer_openrazer_offer_fakes import (
    UBUNTU_OS,
    make_native_absent,
    offer_harness,
    stage_native_helper_local,
    stage_native_helper_remote,
    write_os,
)
from tests.openrazer_installer_fakes import TAG


def test_successful_native_enables_only_and_keeps_profiles(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    make_native_absent(fake, UBUNTU_OS)
    stage_native_helper_local(fake, script)
    profile = fake.root / "home/.config/naga-control/profiles.toml"
    profile.parent.mkdir(parents=True)
    profile.write_text("user profile untouched\n")
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n")
        result, commands = fake.run(
            "--version", TAG, "--restart-service", script=script, input_fd=slave
        )
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode == 0, result.stderr + result.stdout
    assert "installation staged:" in result.stdout
    assert "reboot/re-login" in result.stdout
    assert ["systemctl", "--user", "enable", "naga-control.service"] in commands
    assert not any("--now" in c for c in commands)
    assert profile.read_text() == "user profile untouched\n"
    assert stamp(fake).read_text() == TAG + "\n"
    assert installed_image(fake).read_bytes() == (fake.remote / ASSET).read_bytes()
    assert_private_cleanup(fake)


def test_native_preflight_failure_leaves_naga_unchanged(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    make_native_absent(fake, UBUNTU_OS)
    previous = seed_previous(fake)
    stage_native_helper_local(fake, script)
    fake.configure(helper_preflight_failure=1)
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n")
        result, commands = fake.run(
            "--version", TAG, "--restart-service", script=script, input_fd=slave
        )
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode != 0
    assert "OpenRazer prerequisite preflight failed" in result.stderr
    assert installed_image(fake).read_bytes() == previous
    assert not any(c[0] == "installer-helper" and "--install" in c for c in commands)
    assert_private_cleanup(fake)


def test_native_explicit_preflight_failure_before_stop(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    write_os(fake, UBUNTU_OS)
    fake.configure(installed={}, stamps={}, python_root=False, python_client=False)
    fake.configure(python_daemon=False, dpkg_installed={}, rpm_installed={})
    previous = seed_previous(fake)
    stage_native_helper_local(fake, script)
    fake.configure(helper_preflight_failure=1)
    result, commands = fake.run(
        "--version", TAG, "--install-openrazer", "--restart-service", script=script
    )
    assert result.returncode != 0
    assert "OpenRazer prerequisite preflight failed" in result.stderr
    assert installed_image(fake).read_bytes() == previous
    assert ["systemctl", "--user", "stop", "naga-control.service"] not in commands
    assert_private_cleanup(fake)


def test_native_install_failure_verified_stays_stopped(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    make_native_absent(fake, UBUNTU_OS)
    seed_previous(fake)
    stage_native_helper_local(fake, script)
    fake.configure(helper_install_failure=1)
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n")
        result, commands = fake.run(
            "--version", TAG, "--restart-service", script=script, input_fd=slave
        )
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode != 0
    assert "Naga remains stopped" in result.stderr or "possible partial" in result.stderr
    assert not any("--now" in c for c in commands)
    assert_private_cleanup(fake)


def test_native_install_failure_unverified_keeps_quarantine(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    make_native_absent(fake, UBUNTU_OS)
    _old, _altered = seed_altered_previous(fake)
    stage_native_helper_local(fake, script)
    fake.configure(helper_install_failure=1)
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n")
        result, _commands = fake.run(
            "--version", TAG, "--restart-service", script=script, input_fd=slave
        )
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode != 0
    assert "unverified" in result.stderr.lower() or "manual recovery" in result.stderr.lower()
    parent = stamp(fake).parent
    kept = list(parent.glob("quarantine.*")) + list(parent.glob("rollback.*"))
    assert kept, "expected retained quarantine/rollback for manual recovery"


def test_native_phase_order_preflight_stop_install(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    make_native_absent(fake, UBUNTU_OS)
    seed_previous(fake)
    stage_native_helper_local(fake, script)
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n")
        result, commands = fake.run(
            "--version",
            TAG,
            "--install-openrazer",
            "--restart-service",
            script=script,
            input_fd=slave,
        )
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode == 0, result.stderr
    helpers = [c for c in commands if c[0] == "installer-helper"]
    assert len(helpers) == 2
    assert helpers[0][-1] == "--preflight"
    assert helpers[1][-1] == "--install"
    assert "--family" in helpers[0] and "--code-ref" in helpers[0]
    stop = commands.index(["systemctl", "--user", "stop", "naga-control.service"])
    preflight = commands.index(helpers[0])
    install = commands.index(helpers[1])
    execution = next(i for i, c in enumerate(commands) if c[0] == ASSET)
    assert preflight < stop < install < execution
    assert_private_cleanup(fake)


def test_remote_native_success_uses_sha_code_ref(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    make_native_absent(fake, UBUNTU_OS)
    stage_native_helper_remote(fake)
    fake.configure(naga_sha="c" * 40)
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n")
        result, commands = fake.run("--version", TAG, script=script, input_fd=slave)
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode == 0, result.stderr + result.stdout
    helpers = [c for c in commands if c[0] == "installer-helper"]
    assert helpers and ("c" * 40) in " ".join(helpers[0])
    assert ["systemctl", "--user", "enable", "naga-control.service"] in commands
    assert_private_cleanup(fake)
