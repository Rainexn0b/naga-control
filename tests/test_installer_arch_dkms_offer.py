"""Arch DKMS offer: separate consent for missing DKMS before preflight."""

import os
import pty
from pathlib import Path

from tests.installer_app_fakes import (
    ASSET,
    HELPER_OK,
    assert_private_cleanup,
    installed_image,
    seed_previous,
    stamp,
)
from tests.installer_openrazer_offer_fakes import (
    make_arch_absent,
    offer_harness,
)
from tests.openrazer_installer_fakes import TAG, InstallerHarness


def make_dkms_absent(fake: InstallerHarness) -> None:
    (fake.root / "bin/dkms").unlink()


def test_explicit_flag_absent_dkms_accepts_before_preflight(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path, helper=HELPER_OK)
    make_arch_absent(fake)
    make_dkms_absent(fake)
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n")
        result, commands = fake.run(
            "--version", TAG, "--install-openrazer", script=script, input_fd=slave
        )
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode == 0, result.stderr + result.stdout
    assert "DKMS tool" in result.stdout
    assert "sudo pacman -S --needed dkms" in result.stdout
    assert "fake prerequisite preflight" in result.stdout
    dkms = ["sudo", "pacman", "-S", "--needed", "dkms"]
    assert dkms in commands
    preflight = commands.index(["installer-helper", "--version", TAG, "--preflight"])
    assert commands.index(dkms) < preflight
    assert ["systemctl", "--user", "enable", "naga-control.service"] in commands
    assert not any("--now" in c for c in commands)
    assert_private_cleanup(fake)


def test_explicit_env1_absent_dkms_accepts(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path, helper=HELPER_OK)
    make_arch_absent(fake)
    make_dkms_absent(fake)
    fake.environment["NAGA_CONTROL_INSTALL_OPENRAZER"] = "1"
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n")
        result, commands = fake.run("--version", TAG, script=script, input_fd=slave)
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode == 0, result.stderr + result.stdout
    assert ["sudo", "pacman", "-S", "--needed", "dkms"] in commands
    assert "fake prerequisite preflight" in result.stdout
    assert_private_cleanup(fake)


def test_automatic_offer_absent_dkms_accepts_before_preflight(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path, helper=HELPER_OK)
    make_arch_absent(fake)
    make_dkms_absent(fake)
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\ny\n")
        result, commands = fake.run("--version", TAG, script=script, input_fd=slave)
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode == 0, result.stderr + result.stdout
    assert "Experimental Arch setup offers pinned cohort" in result.stdout
    assert "sudo pacman -S --needed dkms" in result.stdout
    assert "fake prerequisite called" in result.stdout
    assert "installation staged:" in result.stdout
    dkms = ["sudo", "pacman", "-S", "--needed", "dkms"]
    assert dkms in commands
    preflight = commands.index(["installer-helper", "--version", TAG, "--preflight"])
    assert commands.index(dkms) < preflight
    assert not any("--now" in c for c in commands)
    assert_private_cleanup(fake)


def test_dkms_present_explicit_needs_no_extra_transaction(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path, helper=HELPER_OK)
    make_arch_absent(fake)
    assert (fake.root / "bin/dkms").is_file()
    result, commands = fake.run("--version", TAG, "--install-openrazer", script=script)
    assert result.returncode == 0, result.stderr
    assert "fake prerequisite preflight" in result.stdout
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert_private_cleanup(fake)


def test_dkms_present_automatic_needs_single_consent(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path, helper=HELPER_OK)
    make_arch_absent(fake)
    assert (fake.root / "bin/dkms").is_file()
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n")
        result, commands = fake.run("--version", TAG, script=script, input_fd=slave)
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode == 0, result.stderr
    assert "fake prerequisite called" in result.stdout
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert_private_cleanup(fake)


def test_real_helper_absent_dkms_keeps_pinned_transaction_distinct(
    tmp_path: Path,
) -> None:
    fake, script = offer_harness(tmp_path)
    make_arch_absent(fake)
    make_dkms_absent(fake)
    fake.stage_openrazer(script.parent / "install_openrazer.sh")
    profile = fake.root / "home/.config/naga-control/profiles.toml"
    profile.parent.mkdir(parents=True)
    profile.write_text("user profile untouched\n")
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\ny\ny\n")
        result, commands = fake.run(
            "--version", TAG, "--restart-service", script=script, input_fd=slave
        )
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode == 0, result.stderr + result.stdout
    assert "Read-only install preflight passed" in result.stdout
    assert "installation staged:" in result.stdout
    dkms = ["sudo", "pacman", "-S", "--needed", "dkms"]
    assert dkms in commands
    assert len(dkms) == 5
    transaction = next(c for c in commands if c[:2] == ["sudo", "pacman"] and c[2] == "-U")
    assert len(transaction) == 6
    assert len(transaction[3:]) == 3
    assert commands.index(dkms) < commands.index(transaction)
    preflight = next(
        i
        for i, c in enumerate(commands)
        if c[0] == "system-python3" and any("sys.version_info" in a for a in c)
    )
    assert commands.index(dkms) < preflight < commands.index(transaction)
    assert profile.read_text() == "user profile untouched\n"
    assert stamp(fake).read_text() == TAG + "\n"
    assert installed_image(fake).read_bytes() == (fake.remote / ASSET).read_bytes()
    assert_private_cleanup(fake)


def test_missing_helper_still_fetched_from_selected_release_with_dkms(
    tmp_path: Path,
) -> None:
    fake, script = offer_harness(tmp_path)
    make_arch_absent(fake)
    make_dkms_absent(fake)
    (fake.remote / "install_openrazer.sh").write_text(HELPER_OK)
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
    urls = [
        item for command in commands if command[0] == "curl" for item in command if "https:" in item
    ]
    assert (
        urls[-1]
        == f"https://raw.githubusercontent.com/Rainexn0b/naga-control/{TAG}/scripts/install_openrazer.sh"
    )
    assert ["sudo", "pacman", "-S", "--needed", "dkms"] in commands
    assert_private_cleanup(fake)


def test_dkms_success_preserves_separate_group_consent(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    make_arch_absent(fake)
    make_dkms_absent(fake)
    fake.configure(groups="users")
    fake.stage_openrazer(script.parent / "install_openrazer.sh")
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\ny\ny\ny\n")
        result, commands = fake.run(
            "--version", TAG, "--restart-service", script=script, input_fd=slave
        )
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode == 0, result.stderr + result.stdout
    assert ["sudo", "pacman", "-S", "--needed", "dkms"] in commands
    assert ["sudo", "usermod", "-aG", "openrazer", "desktop-user"] in commands
    assert commands.index(["sudo", "pacman", "-S", "--needed", "dkms"]) < commands.index(
        ["sudo", "usermod", "-aG", "openrazer", "desktop-user"]
    )
    assert not any("--now" in c for c in commands)


def test_accepted_dkms_with_active_naga_orders_stop_before_transaction(
    tmp_path: Path,
) -> None:
    fake, script = offer_harness(tmp_path)
    make_arch_absent(fake)
    make_dkms_absent(fake)
    seed_previous(fake)
    fake.stage_openrazer(script.parent / "install_openrazer.sh")
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\ny\ny\n")
        result, commands = fake.run(
            "--version", TAG, "--restart-service", script=script, input_fd=slave
        )
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode == 0, result.stderr + result.stdout
    assert "installation staged:" in result.stdout
    dkms = ["sudo", "pacman", "-S", "--needed", "dkms"]
    stop = ["systemctl", "--user", "stop", "naga-control.service"]
    assert dkms in commands
    assert stop in commands
    transaction = next(c for c in commands if c[:2] == ["sudo", "pacman"] and c[2] == "-U")
    assert len(transaction) == 6
    dkms_idx = commands.index(dkms)
    preflight = next(
        i
        for i, c in enumerate(commands)
        if c[0] == "system-python3" and any("sys.version_info" in a for a in c) and i > dkms_idx
    )
    assert dkms_idx < preflight
    assert preflight < commands.index(stop) < commands.index(transaction)
    assert not any("--now" in c for c in commands)
