"""Offer safety: preserve working backends, unknown skips, hostile OS, failures."""

import os
import pty
from pathlib import Path
from typing import Any

import pytest

from tests.installer_app_fakes import (
    ASSET,
    HELPER_OK,
    app_harness,
    assert_private_cleanup,
    installed_image,
    mutations,
    seed_previous,
)
from tests.installer_openrazer_offer_fakes import (
    ARCH_OS,
    UBUNTU_OS,
    make_arch_absent,
    offer_harness,
    stage_native_helper_local,
    write_os,
)
from tests.openrazer_installer_fakes import PIN, ROLES, TAG, VERSION, InstallerHarness


def _arch_present(
    fake: InstallerHarness,
    installed: dict[Any, Any],
    python_client: bool = True,
    python_daemon: bool = True,
) -> None:
    write_os(fake, ARCH_OS)
    stamps = {k: PIN for k in installed if k in ROLES}
    fake.configure(installed=installed, stamps=stamps)
    fake.configure(python_client=python_client, python_daemon=python_daemon)


def test_present_backends_never_offered(tmp_path: Path) -> None:
    cases = [
        dict.fromkeys(ROLES, VERSION),
        {r.removesuffix("-local"): "3.12.1-1" for r in ROLES},
        {ROLES[0]: VERSION},
        {ROLES[0]: VERSION, ROLES[1]: "3.12.1.pr2904.fix1-1"},
    ]
    for index, installed in enumerate(cases):
        case_dir = tmp_path / f"case{index}"
        case_dir.mkdir()
        fake, script = offer_harness(case_dir)
        _arch_present(fake, installed)
        result, commands = fake.run("--version", TAG, script=script)
        assert result.returncode == 0, result.stderr
        assert "app-only install" in result.stdout
        assert "leaving it unchanged" in result.stdout
        assert "Install experimental pinned OpenRazer" not in result.stdout
        assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
        assert ["systemctl", "--user", "enable", "--now", "naga-control.service"] in commands
        assert_private_cleanup(fake)


def test_client_only_source_discovery_never_offered(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    write_os(fake, ARCH_OS)
    fake.configure(installed={}, stamps={}, python_client=True, python_daemon=True)
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "leaving it unchanged" in result.stdout
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert_private_cleanup(fake)


@pytest.mark.parametrize(
    "setup",
    ["inventory-error", "python-error", "python-unknown", "python-missing"],
)
def test_unknown_detection_skips_offer_safely(tmp_path: Path, setup: str) -> None:
    fake, script = offer_harness(tmp_path)
    make_arch_absent(fake)
    if setup == "inventory-error":
        fake.configure(pacman_inventory_error=1)
    elif setup == "python-error":
        fake.configure(python_discover_error=1)
    elif setup == "python-unknown":
        fake.configure(python_unknown=1)
    else:
        (fake.root / "bin/system-python3").unlink()
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "app-only install" in result.stdout
    assert "unknown or host not eligible" in result.stdout
    assert "--install-openrazer" in result.stdout
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert_private_cleanup(fake)


def test_nonarch_with_pacman_never_offers(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    write_os(fake, UBUNTU_OS)
    fake.configure(
        installed={ROLES[0]: VERSION},
        stamps={ROLES[0]: PIN},
        python_client=False,
        python_daemon=False,
    )
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "app-only install" in result.stdout
    assert ["pacman", "-Q"] not in commands
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert_private_cleanup(fake)


@pytest.mark.parametrize(
    "os_text",
    [
        "ID=arch\nID=arch\n",
        "ID=arch\nID_LIKE=arch\nID_LIKE=arch\n",
        'ID="arch\n',
        "ID=$(reboot)\n",
        "ID=ARCH\n",
        "ID_LIKE=arch debian\n",
        "ID=ubuntu\nID_LIKE=arch\n",
        "NAME=test\n",
        "",
    ],
)
def test_hostile_or_ambiguous_os_never_offers(tmp_path: Path, os_text: str) -> None:
    fake, script = offer_harness(tmp_path)
    write_os(fake, os_text)
    fake.configure(installed={}, stamps={}, python_client=False, python_daemon=False)
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "app-only install" in result.stdout
    assert ["pacman", "-Q"] not in commands
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert_private_cleanup(fake)


def test_nul_and_control_os_never_offers(tmp_path: Path) -> None:
    first = tmp_path / "first"
    first.mkdir()
    fake, script = offer_harness(first)
    write_os(fake, b"ID=arch\nID_LIKE=arch\x00\n")
    fake.configure(installed={}, stamps={}, python_client=False, python_daemon=False)
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert ["pacman", "-Q"] not in commands
    assert_private_cleanup(fake)
    second = tmp_path / "second"
    second.mkdir()
    fake2, script2 = offer_harness(second)
    write_os(fake2, "ID=arch\x01\n")
    fake2.configure(installed={}, stamps={}, python_client=False, python_daemon=False)
    result2, commands2 = fake2.run("--version", TAG, script=script2)
    assert result2.returncode == 0, result2.stderr
    assert ["pacman", "-Q"] not in commands2
    assert_private_cleanup(fake2)


def test_oversized_os_never_offers(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    write_os(fake, "ID=arch\n" + "A" * 5000 + "\n")
    fake.configure(installed={}, stamps={}, python_client=False, python_daemon=False)
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert ["pacman", "-Q"] not in commands
    assert_private_cleanup(fake)


def test_fallback_only_when_etc_absent(tmp_path: Path) -> None:
    first = tmp_path / "first"
    first.mkdir()
    fake, script = offer_harness(first)
    (fake.root / "os-release").unlink()
    (fake.root / "vendor-os-release").write_text(ARCH_OS)
    fake.configure(installed={}, stamps={}, python_client=False, python_daemon=False)
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
    second = tmp_path / "second"
    second.mkdir()
    fake2, script2 = offer_harness(second)
    write_os(fake2, "ID=arch\nID=arch\n", vendor=ARCH_OS)
    fake2.configure(installed={}, stamps={}, python_client=False, python_daemon=False)
    result2, commands2 = fake2.run("--version", TAG, script=script2)
    assert result2.returncode == 0, result2.stderr
    assert ["pacman", "-Q"] not in commands2
    assert_private_cleanup(fake2)


def test_hard_new_image_failure_never_prompts(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path, helper=HELPER_OK)
    make_arch_absent(fake)
    (fake.remote / ASSET).write_bytes(b"tampered-new")
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n")
        result, commands = fake.run("--version", TAG, script=script, input_fd=slave)
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr
    assert "Install experimental pinned OpenRazer" not in result.stdout
    assert ["pacman", "-Q"] not in commands
    assert mutations(commands) == []
    assert not installed_image(fake).exists()
    assert_private_cleanup(fake)


def test_offer_yes_preflight_failure_leaves_naga_unchanged(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    make_arch_absent(fake)
    previous = seed_previous(fake)
    fake.stage_openrazer(script.parent / "install_openrazer.sh")
    fake.configure(host_python="3.8")
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
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert_private_cleanup(fake)


def test_offer_yes_package_failure_stays_stopped(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    make_arch_absent(fake)
    seed_previous(fake)
    fake.stage_openrazer(script.parent / "install_openrazer.sh")
    fake.configure(pacman_failure=1)
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\ny\n")
        result, commands = fake.run(
            "--version", TAG, "--restart-service", script=script, input_fd=slave
        )
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode != 0
    assert "pacman transaction failed" in result.stderr
    assert "Naga remains stopped" in result.stderr
    assert not any("--now" in c for c in commands)
    assert_private_cleanup(fake)


def test_explicit_flag_on_ubuntu_runs_native_helper(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    write_os(fake, UBUNTU_OS)
    fake.configure(
        installed={}, stamps={}, python_root=False, python_client=False, python_daemon=False
    )
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
    assert "family=debian" in result.stdout
    assert any(c[0] == "installer-helper" and "--family" in c for c in commands)
    assert_private_cleanup(fake)


def test_new_image_hash_is_canonical_before_offer(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    manifest = fake.remote / (ASSET + ".sha256")
    row = manifest.read_text()
    manifest.write_bytes((row + row).encode())
    fake.configure(service_state="active")
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n")
        result, commands = fake.run("--version", TAG, script=script, input_fd=slave)
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode != 0
    assert ["pacman", "-Q"] not in commands
    assert mutations(commands) == []
    assert_private_cleanup(fake)
