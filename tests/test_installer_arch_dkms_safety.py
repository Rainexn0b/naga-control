"""Arch DKMS safety: declines, failures, skips, and preserved backends."""

import json
import os
import pty
from pathlib import Path

from tests.installer_app_fakes import (
    HELPER_OK,
    USER_FILES,
    assert_private_cleanup,
    installed_image,
    mutations,
    seed_previous,
    stamp,
)
from tests.installer_openrazer_offer_fakes import (
    ARCH_OS,
    RHEL_OS,
    UBUNTU_OS,
    make_arch_absent,
    make_ubuntu_absent,
    offer_harness,
    stage_native_helper_local,
    write_os,
)
from tests.openrazer_installer_fakes import PIN, ROLES, TAG, VERSION, InstallerHarness


def make_dkms_absent(fake: InstallerHarness) -> None:
    (fake.root / "bin/dkms").unlink()


def test_dkms_decline_aborts_before_stop_without_mutation(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path, helper=HELPER_OK)
    make_arch_absent(fake)
    make_dkms_absent(fake)
    previous = seed_previous(fake)
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\nn\n")
        result, commands = fake.run(
            "--version", TAG, "--restart-service", script=script, input_fd=slave
        )
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode != 0
    assert "DKMS prerequisite declined" in result.stderr
    assert "Naga unchanged" in result.stderr
    assert installed_image(fake).read_bytes() == previous
    assert stamp(fake).read_text() != TAG + "\n"
    assert mutations(commands) == []
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert_private_cleanup(fake)


def test_explicit_dkms_decline_aborts_without_stop(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path, helper=HELPER_OK)
    make_arch_absent(fake)
    make_dkms_absent(fake)
    previous = seed_previous(fake)
    master, slave = pty.openpty()
    try:
        os.write(master, b"n\n")
        result, commands = fake.run(
            "--version", TAG, "--install-openrazer", script=script, input_fd=slave
        )
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode != 0
    assert "DKMS prerequisite declined" in result.stderr
    assert installed_image(fake).read_bytes() == previous
    assert mutations(commands) == []
    assert_private_cleanup(fake)


def test_dkms_eof_aborts_before_stop(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path, helper=HELPER_OK)
    make_arch_absent(fake)
    make_dkms_absent(fake)
    previous = seed_previous(fake)
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n\x04")
        result, commands = fake.run(
            "--version", TAG, "--restart-service", script=script, input_fd=slave
        )
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode != 0
    assert "DKMS prerequisite declined" in result.stderr
    assert installed_image(fake).read_bytes() == previous
    assert mutations(commands) == []
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert_private_cleanup(fake)


def test_explicit_dkms_nontty_aborts_without_install(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path, helper=HELPER_OK)
    make_arch_absent(fake)
    make_dkms_absent(fake)
    previous = seed_previous(fake)
    result, commands = fake.run("--version", TAG, "--install-openrazer", script=script)
    assert result.returncode != 0
    assert "terminal for separate consent" in result.stderr
    assert "Naga unchanged" in result.stderr
    assert installed_image(fake).read_bytes() == previous
    assert mutations(commands) == []
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert_private_cleanup(fake)


def test_dkms_pacman_failure_leaves_naga_unchanged_without_stop(
    tmp_path: Path,
) -> None:
    fake, script = offer_harness(tmp_path, helper=HELPER_OK)
    make_arch_absent(fake)
    make_dkms_absent(fake)
    previous = seed_previous(fake)
    fake.configure(dkms_pacman_failure=1)
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n")
        result, commands = fake.run(
            "--version", TAG, "--install-openrazer", script=script, input_fd=slave
        )
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode != 0
    assert "DKMS prerequisite install failed" in result.stderr
    assert "possible partial package changes" in result.stderr
    assert "Naga unchanged" in result.stderr
    assert installed_image(fake).read_bytes() == previous
    assert ["sudo", "pacman", "-S", "--needed", "dkms"] in commands
    assert not any(c[:3] == ["sudo", "pacman", "-U"] for c in commands)
    assert ["systemctl", "--user", "stop", "naga-control.service"] not in commands
    assert mutations(commands) == [["sudo", "pacman", "-S", "--needed", "dkms"]]
    assert not (fake.root / "installed.rules").exists()
    assert json.loads((fake.root / "state.json").read_text())["service_state"] == "active"
    assert not any(c[0] == "installer-helper" for c in commands)
    assert_private_cleanup(fake)


def test_dkms_no_executable_after_success_aborts(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path, helper=HELPER_OK)
    make_arch_absent(fake)
    make_dkms_absent(fake)
    previous = seed_previous(fake)
    fake.configure(dkms_no_executable=True)
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n")
        result, commands = fake.run(
            "--version", TAG, "--install-openrazer", script=script, input_fd=slave
        )
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode != 0
    assert "still missing after the prerequisite transaction" in result.stderr
    assert installed_image(fake).read_bytes() == previous
    assert ["sudo", "pacman", "-S", "--needed", "dkms"] in commands
    assert mutations(commands) == [["sudo", "pacman", "-S", "--needed", "dkms"]]
    assert_private_cleanup(fake)


def test_env0_hard_skips_no_dkms_prompt_or_inventory(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    make_arch_absent(fake)
    make_dkms_absent(fake)
    (fake.remote / "install_openrazer.sh").write_text(HELPER_OK)
    fake.environment["NAGA_CONTROL_INSTALL_OPENRAZER"] = "0"
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "hard skip" in result.stdout
    assert not any(c[0] == "pacman" for c in commands)
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert not any("install_openrazer.sh" in item for c in commands for item in c if c[0] == "curl")
    assert_private_cleanup(fake)


def test_initial_offer_decline_never_reaches_dkms(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    make_arch_absent(fake)
    make_dkms_absent(fake)
    (fake.remote / "install_openrazer.sh").write_text(HELPER_OK)
    master, slave = pty.openpty()
    try:
        os.write(master, b"n\n")
        result, commands = fake.run("--version", TAG, script=script, input_fd=slave)
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode == 0, result.stderr
    assert "app-only install" in result.stdout
    assert "DKMS" not in result.stdout
    assert "DKMS" not in result.stderr
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert not any("install_openrazer.sh" in item for c in commands for item in c if c[0] == "curl")
    assert ["systemctl", "--user", "stop", "naga-control.service"] not in commands
    assert ["systemctl", "--user", "enable", "--now", "naga-control.service"] in commands
    assert_private_cleanup(fake)


def test_env0_with_flag_hard_skips_without_dkms_or_fetch(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    make_arch_absent(fake)
    make_dkms_absent(fake)
    (fake.remote / "install_openrazer.sh").write_text(HELPER_OK)
    fake.environment["NAGA_CONTROL_INSTALL_OPENRAZER"] = "0"
    result, commands = fake.run("--version", TAG, "--install-openrazer", script=script)
    assert result.returncode == 0, result.stderr
    assert "hard skip" in result.stdout
    assert "app-only install" in result.stdout
    assert "DKMS" not in result.stdout
    assert "DKMS" not in result.stderr
    assert not any(c[0] == "pacman" for c in commands)
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert not any("install_openrazer.sh" in item for c in commands for item in c if c[0] == "curl")
    assert ["systemctl", "--user", "stop", "naga-control.service"] not in commands
    assert_private_cleanup(fake)


def test_present_backend_never_prompts_dkms(tmp_path: Path) -> None:
    cases = (dict.fromkeys(ROLES, VERSION), {ROLES[0]: VERSION})
    for index, installed in enumerate(cases):
        case = tmp_path / f"case{index}"
        case.mkdir()
        fake, script = offer_harness(case)
        write_os(fake, ARCH_OS)
        stamps = {k: PIN for k in installed if k in ROLES}
        fake.configure(installed=installed, stamps=stamps)
        fake.configure(python_client=True, python_daemon=True)
        make_dkms_absent(fake)
        result, commands = fake.run("--version", TAG, script=script)
        assert result.returncode == 0, result.stderr
        assert "leaving it unchanged" in result.stdout
        assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
        assert_private_cleanup(fake)


def test_unknown_backend_never_prompts_dkms(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    make_arch_absent(fake)
    make_dkms_absent(fake)
    fake.configure(pacman_inventory_error=1)
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "unknown or host not eligible" in result.stdout
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert_private_cleanup(fake)


def test_native_and_ineligible_routes_never_prompt_dkms(tmp_path: Path) -> None:
    ubuntu = tmp_path / "ubuntu"
    ubuntu.mkdir()
    fake, script = offer_harness(ubuntu)
    make_ubuntu_absent(fake)
    make_dkms_absent(fake)
    stage_native_helper_local(fake, script)
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n")
        result, commands = fake.run("--version", TAG, script=script, input_fd=slave)
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode == 0, result.stderr
    assert "fake native prerequisite called" in result.stdout
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert_private_cleanup(fake)
    rhel = tmp_path / "rhel"
    rhel.mkdir()
    fake2, script2 = offer_harness(rhel)
    write_os(fake2, RHEL_OS)
    fake2.configure(installed={}, stamps={}, python_client=False, python_daemon=False)
    (fake2.root / "bin/dkms").unlink()
    result2, commands2 = fake2.run("--version", TAG, script=script2)
    assert result2.returncode == 0, result2.stderr
    assert ["pacman", "-Q"] not in commands2
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands2)
    assert_private_cleanup(fake2)


def test_explicit_native_never_prompts_dkms(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    write_os(fake, UBUNTU_OS)
    fake.configure(installed={}, stamps={}, python_client=False, python_daemon=False)
    make_dkms_absent(fake)
    stage_native_helper_local(fake, script)
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n")
        result, commands = fake.run(
            "--version", TAG, "--install-openrazer", script=script, input_fd=slave
        )
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode == 0, result.stderr
    assert "fake native prerequisite called" in result.stdout
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert_private_cleanup(fake)


def test_restart_service_alone_never_prompts_dkms(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    make_arch_absent(fake)
    make_dkms_absent(fake)
    result, commands = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    assert "app-only install" in result.stdout
    assert ["systemctl", "--user", "enable", "--now", "naga-control.service"] in commands
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert_private_cleanup(fake)


def test_other_arch_preflight_gates_still_manual(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    make_arch_absent(fake)
    assert (fake.root / "bin/dkms").is_file()
    previous = seed_previous(fake)
    fake.stage_openrazer(script.parent / "install_openrazer.sh")
    (fake.root / "modules/fake-kernel/build/.config").unlink()
    result, commands = fake.run(
        "--version", TAG, "--install-openrazer", "--restart-service", script=script
    )
    assert result.returncode != 0
    assert "OpenRazer prerequisite preflight failed" in result.stderr
    assert installed_image(fake).read_bytes() == previous
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert mutations(commands) == []
    assert_private_cleanup(fake)


def test_dkms_failure_preserves_profiles_and_no_udev_change(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path, helper=HELPER_OK)
    make_arch_absent(fake)
    make_dkms_absent(fake)
    previous = seed_previous(fake)
    profile = fake.root / "home/.config/naga-control/profiles.toml"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text("user profile untouched\n")
    before = json.loads((fake.root / "state.json").read_text())
    fake.configure(dkms_pacman_failure=1)
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n")
        result, _commands = fake.run(
            "--version", TAG, "--install-openrazer", script=script, input_fd=slave
        )
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode != 0
    assert profile.read_text() == "user profile untouched\n"
    assert installed_image(fake).read_bytes() == previous
    after = json.loads((fake.root / "state.json").read_text())
    assert after["service_state"] == before["service_state"]
    for relative in USER_FILES:
        assert (fake.root / "home" / relative).read_text() == "previous integration\n"
    assert not (fake.root / "installed.rules").exists()
    assert_private_cleanup(fake)
