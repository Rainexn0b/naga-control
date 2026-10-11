"""Default OpenRazer offer: consent-gated setup on eligible Arch when absent."""

import os
import pty
from pathlib import Path

import pytest

from tests.installer_app_fakes import (
    ASSET,
    HELPER_OK,
    app_harness,
    assert_private_cleanup,
    installed_image,
    stamp,
)
from tests.installer_openrazer_offer_fakes import (
    RHEL_OS,
    make_arch_absent,
    make_derivative_absent,
    offer_harness,
    write_os,
)
from tests.openrazer_installer_fakes import TAG


def test_default_ineligible_stays_app_only_without_inventory_queries(
    tmp_path: Path,
) -> None:
    fake, script = app_harness(tmp_path)
    write_os(fake, RHEL_OS)
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "app-only install" in result.stdout
    assert ["systemctl", "--user", "enable", "--now", "naga-control.service"] in commands
    assert ["pacman", "-Q"] not in commands
    assert not any(c[0] == "dpkg-query" for c in commands)
    assert not any(c[0] == "rpm" and c[1] == "-qa" for c in commands)
    assert not any(c[0] == "system-python3" and "PathFinder" in " ".join(c) for c in commands)
    assert_private_cleanup(fake)


def test_offer_no_leaves_app_only_without_helper_fetch(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    make_arch_absent(fake)
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
    assert "OpenRazer is not installed" in result.stdout
    assert "--install-openrazer" in result.stdout
    assert ["systemctl", "--user", "enable", "--now", "naga-control.service"] in commands
    assert not any("install_openrazer.sh" in item for c in commands for item in c if c[0] == "curl")
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert not any(c[:2] == ["sudo", "usermod"] for c in commands)
    assert_private_cleanup(fake)


def test_offer_eof_leaves_app_only(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    make_arch_absent(fake)
    master, slave = pty.openpty()
    os.close(master)
    try:
        result, commands = fake.run("--version", TAG, script=script, input_fd=slave)
    finally:
        os.close(slave)
    assert result.returncode == 0, result.stderr
    assert "app-only install" in result.stdout
    assert "OpenRazer is not installed" in result.stdout
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert not any(c[:2] == ["sudo", "usermod"] for c in commands)
    assert_private_cleanup(fake)


def test_offer_no_tty_leaves_app_only_without_prompt_consumption(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    make_arch_absent(fake)
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "app-only install" in result.stdout
    assert "OpenRazer is not installed" in result.stdout
    assert "--install-openrazer" in result.stdout
    assert "experimental Arch" in result.stdout
    assert ["systemctl", "--user", "enable", "--now", "naga-control.service"] in commands
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert not any(c[:2] == ["sudo", "usermod"] for c in commands)
    assert_private_cleanup(fake)


def test_offer_yes_with_real_helper_stages_cohort(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    make_arch_absent(fake)
    fake.stage_openrazer(script.parent / "install_openrazer.sh")
    profile = fake.root / "home/.config/naga-control/profiles.toml"
    profile.parent.mkdir(parents=True)
    profile.write_text("user profile untouched\n")
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\ny\n")
        result, commands = fake.run(
            "--version", TAG, "--restart-service", script=script, input_fd=slave
        )
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode == 0, result.stderr + result.stdout
    assert (
        "checking optional OpenRazer install prerequisites before Naga stop consent"
        in result.stdout
    )
    assert "Read-only install preflight passed" in result.stdout
    assert "installation staged:" in result.stdout
    assert "reboot/re-login" in result.stdout
    assert not any("--now" in c for c in commands)
    transaction = next(c for c in commands if c[:2] == ["sudo", "pacman"])
    assert len(transaction) == 6
    assert len(transaction[3:]) == 3
    preflight = next(
        i
        for i, c in enumerate(commands)
        if c[0] == "system-python3" and any("sys.exit" in a for a in c)
    )
    package = commands.index(transaction)
    assert preflight < package
    assert profile.read_text() == "user profile untouched\n"
    assert stamp(fake).read_text() == TAG + "\n"
    assert installed_image(fake).read_bytes() == (fake.remote / ASSET).read_bytes()
    assert_private_cleanup(fake)


def test_derivative_absent_offers_with_consent(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path, helper=HELPER_OK)
    make_derivative_absent(fake)
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n")
        result, _commands = fake.run("--version", TAG, script=script, input_fd=slave)
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode == 0, result.stderr
    assert "fake prerequisite called" in result.stdout
    assert "installation staged:" in result.stdout
    assert_private_cleanup(fake)


@pytest.mark.parametrize("opt_in", ["flag", "env1"])
def test_explicit_opt_in_has_no_redundant_offer(tmp_path: Path, opt_in: str) -> None:
    fake, script = offer_harness(tmp_path, helper=HELPER_OK)
    make_arch_absent(fake)
    args = ["--version", TAG, "--install-openrazer"] if opt_in == "flag" else ["--version", TAG]
    if opt_in == "env1":
        fake.environment["NAGA_CONTROL_INSTALL_OPENRAZER"] = "1"
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n")
        result, commands = fake.run(*args, script=script, input_fd=slave)
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode == 0, result.stderr
    assert "fake prerequisite called" in result.stdout
    assert "Install experimental pinned OpenRazer" not in result.stdout
    assert ["pacman", "-Q"] not in commands


@pytest.mark.parametrize("opt_in", ["env0", "env0-flag"])
def test_env_zero_hard_skips_inventory_prompt_and_fetch(tmp_path: Path, opt_in: str) -> None:
    fake, script = offer_harness(tmp_path)
    make_arch_absent(fake)
    (fake.remote / "install_openrazer.sh").write_text(HELPER_OK)
    args = ["--version", TAG]
    if "flag" in opt_in:
        args.append("--install-openrazer")
    fake.environment["NAGA_CONTROL_INSTALL_OPENRAZER"] = "0"
    result, commands = fake.run(*args, script=script)
    assert result.returncode == 0, result.stderr
    assert "hard skip" in result.stdout
    assert "app-only install" in result.stdout
    assert not any(c[0] == "pacman" for c in commands)
    assert not any(c[0] == "system-python3" and "PathFinder" in " ".join(c) for c in commands)
    assert not any("install_openrazer.sh" in item for c in commands for item in c if c[0] == "curl")
    assert_private_cleanup(fake)


def test_restart_service_does_not_consent_to_offer(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    make_arch_absent(fake)
    result, commands = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    assert "app-only install" in result.stdout
    assert "OpenRazer is not installed" in result.stdout
    assert ["systemctl", "--user", "enable", "--now", "naga-control.service"] in commands


@pytest.mark.parametrize(
    "os_text",
    [
        'ID="arch"\n',
        "ID='arch'\n",
        'ID="archlinux"\n',
        'ID=endeavouros\nID_LIKE="arch"\n',
        "ID=endeavouros\nID_LIKE='arch'\n",
    ],
)
def test_quoted_arch_identities_offer_when_absent(tmp_path: Path, os_text: str) -> None:
    fake, script = offer_harness(tmp_path)
    write_os(fake, os_text)
    fake.configure(
        installed={}, stamps={}, python_root=False, python_client=False, python_daemon=False
    )
    master, slave = pty.openpty()
    try:
        os.write(master, b"n\n")
        result, commands = fake.run("--version", TAG, script=script, input_fd=slave)
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode == 0, result.stderr
    assert "OpenRazer is not installed" in result.stdout
    assert ["pacman", "-Q"] in commands
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert_private_cleanup(fake)


def test_quoted_multiword_with_nonarch_rejects(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    write_os(fake, 'ID=custom\nID_LIKE="arch debian"\n')
    fake.configure(
        installed={}, stamps={}, python_root=False, python_client=False, python_daemon=False
    )
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "app-only install" in result.stdout
    assert ["pacman", "-Q"] not in commands
    assert_private_cleanup(fake)


@pytest.mark.parametrize(
    "os_text",
    ["ID=arch\r\n", "ID=arch", 'ID="arch"\r\n', "ID=arch\nID_LIKE=arch"],
)
def test_crlf_and_no_final_newline_valid(tmp_path: Path, os_text: str) -> None:
    fake, script = offer_harness(tmp_path)
    write_os(fake, os_text)
    fake.configure(
        installed={}, stamps={}, python_root=False, python_client=False, python_daemon=False
    )
    master, slave = pty.openpty()
    try:
        os.write(master, b"n\n")
        result, commands = fake.run("--version", TAG, script=script, input_fd=slave)
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode == 0, result.stderr
    assert "OpenRazer is not installed" in result.stdout
    assert ["pacman", "-Q"] in commands
    assert_private_cleanup(fake)


def test_unicode_name_within_limit_allowed(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    smile = "\U0001f600"
    write_os(fake, f'NAME="Arch Linux {smile}"\nID=arch\n')
    fake.configure(
        installed={}, stamps={}, python_root=False, python_client=False, python_daemon=False
    )
    master, slave = pty.openpty()
    try:
        os.write(master, b"n\n")
        result, commands = fake.run("--version", TAG, script=script, input_fd=slave)
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode == 0, result.stderr
    assert "OpenRazer is not installed" in result.stdout
    assert ["pacman", "-Q"] in commands
    assert_private_cleanup(fake)


def test_multibyte_large_ignored_name_rejects_byte_bound(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    smile = "\U0001f600"
    line = 'NAME="' + smile * 1000 + '"\n'
    assert len(line) < 4096
    assert len(line.encode("utf-8")) > 4096 - 100
    text = "ID=arch\n" + line * 20
    assert len(text) < 65537
    assert len(text.encode("utf-8")) > 65537
    write_os(fake, text)
    fake.configure(
        installed={}, stamps={}, python_root=False, python_client=False, python_daemon=False
    )
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "app-only install" in result.stdout
    assert ["pacman", "-Q"] not in commands
    assert_private_cleanup(fake)


def test_multibyte_long_line_rejects_byte_bound(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    smile = "\U0001f600"
    long_name = 'NAME="' + smile * 1500 + '"\n'
    assert len(long_name) < 4096
    assert len(long_name.encode("utf-8")) > 4096
    write_os(fake, "ID=arch\n" + long_name)
    fake.configure(
        installed={}, stamps={}, python_root=False, python_client=False, python_daemon=False
    )
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert ["pacman", "-Q"] not in commands
    assert_private_cleanup(fake)


def test_root_only_partial_preserved(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    write_os(fake, "ID=arch\n")
    fake.configure(
        installed={}, stamps={}, python_root=True, python_client=False, python_daemon=False
    )
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "leaving it unchanged" in result.stdout
    assert "Install experimental pinned OpenRazer" not in result.stdout
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert_private_cleanup(fake)


def test_manual_daemon_launcher_preserved_without_exec(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    write_os(fake, "ID=arch\n")
    fake.configure(
        installed={}, stamps={}, python_root=False, python_client=False, python_daemon=False
    )
    stub = fake.root / "bin/openrazer-daemon"
    stub.write_text('#!/usr/bin/env python3\nimport sys; print("MUST NOT EXECUTE"); sys.exit(99)\n')
    stub.chmod(0o755)
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "leaving it unchanged" in result.stdout
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert not any(c[0] == "openrazer-daemon" for c in commands)
    assert_private_cleanup(fake)


@pytest.mark.parametrize(
    "malformed",
    [
        "OFFER-PROBE openrazer=False client=False daemon=False\nextra",
        "OFFER-PROBE openrazer=False client=False daemon=False ",
        "garbage",
        ["OFFER-PROBE openrazer=False client=False daemon=False", "second"],
    ],
)
def test_malformed_python_output_unknown(tmp_path: Path, malformed: object) -> None:
    fake, script = offer_harness(tmp_path)
    write_os(fake, "ID=arch\n")
    fake.configure(
        installed={}, stamps={}, python_root=False, python_client=False, python_daemon=False
    )
    fake.configure(offer_malformed=malformed)
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "unknown or host not eligible" in result.stdout
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert_private_cleanup(fake)
