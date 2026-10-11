"""Native OpenRazer offer: consent-gated local builds on named families."""

import os
import pty
from pathlib import Path

import pytest

from tests.installer_app_fakes import assert_private_cleanup
from tests.installer_openrazer_offer_fakes import (
    DEBIAN_OS,
    FEDORA_OS,
    LEAP_OS,
    NATIVE_HELPER_OK,
    RHEL_OS,
    SLES_OS,
    TUMBLEWEED_OS,
    UBUNTU_OS,
    make_native_absent,
    offer_harness,
    stage_native_helper_local,
    stage_native_helper_remote,
    write_os,
)
from tests.openrazer_installer_fakes import TAG, InstallerHarness

FAMILIES = [
    (UBUNTU_OS, "debian"),
    (DEBIAN_OS, "debian"),
    (FEDORA_OS, "fedora"),
    (LEAP_OS, "opensuse"),
    (TUMBLEWEED_OS, "opensuse"),
]


def _absent(fake: InstallerHarness, os_text: str) -> None:
    make_native_absent(fake, os_text)


@pytest.mark.parametrize("os_text,family", FAMILIES)
def test_native_offer_no_tty_stays_app_only(tmp_path: Path, os_text: str, family: str) -> None:
    fake, script = offer_harness(tmp_path)
    _absent(fake, os_text)
    stage_native_helper_local(fake, script)
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "app-only install" in result.stdout
    assert "OpenRazer is not installed" in result.stdout
    assert "consented" in result.stdout or "local build" in result.stdout
    if family == "debian":
        assert any(c[0] == "dpkg-query" for c in commands)
        assert not any(c[0] == "rpm" and c[1] == "-qa" for c in commands)
    else:
        assert any(c[0] == "rpm" for c in commands)
        assert not any(c[0] == "dpkg-query" for c in commands)
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert_private_cleanup(fake)


@pytest.mark.parametrize("os_text,family", FAMILIES)
def test_native_offer_decline_stays_app_only(tmp_path: Path, os_text: str, family: str) -> None:
    fake, script = offer_harness(tmp_path)
    _absent(fake, os_text)
    stage_native_helper_local(fake, script)
    master, slave = pty.openpty()
    try:
        os.write(master, b"n\n")
        result, commands = fake.run("--version", TAG, script=script, input_fd=slave)
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode == 0, result.stderr
    assert "app-only install" in result.stdout
    assert not any(
        "install_openrazer_native.sh" in i for c in commands for i in c if c[0] == "curl"
    )
    assert not any(c[0] == "installer-helper" for c in commands)
    assert_private_cleanup(fake)


@pytest.mark.parametrize("os_text,family", FAMILIES)
def test_native_offer_accept_calls_family_helper(tmp_path: Path, os_text: str, family: str) -> None:
    fake, script = offer_harness(tmp_path)
    _absent(fake, os_text)
    stage_native_helper_local(fake, script)
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n")
        result, commands = fake.run("--version", TAG, script=script, input_fd=slave)
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode == 0, result.stderr + result.stdout
    assert "fake native prerequisite called" in result.stdout
    assert f"family={family}" in result.stdout
    helpers = [c for c in commands if c[0] == "installer-helper"]
    assert len(helpers) == 2
    assert helpers[0][1] == "--family" and helpers[0][2] == family
    assert "--code-ref" in helpers[0]
    assert helpers[1][1] == "--family" and helpers[1][2] == family
    assert_private_cleanup(fake)


def test_native_offer_eof_stays_app_only(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    _absent(fake, UBUNTU_OS)
    stage_native_helper_local(fake, script)
    master, slave = pty.openpty()
    os.close(master)
    try:
        result, commands = fake.run("--version", TAG, script=script, input_fd=slave)
    finally:
        os.close(slave)
    assert result.returncode == 0, result.stderr
    assert "app-only install" in result.stdout
    assert not any(c[0] == "installer-helper" for c in commands)
    assert_private_cleanup(fake)


@pytest.mark.parametrize("opt_in", ["env0", "env0-flag"])
def test_native_hard_skip_skips_all_queries(tmp_path: Path, opt_in: str) -> None:
    fake, script = offer_harness(tmp_path)
    _absent(fake, UBUNTU_OS)
    (fake.remote / "install_openrazer_native.sh").write_text(NATIVE_HELPER_OK)
    args = ["--version", TAG]
    if "flag" in opt_in:
        args.append("--install-openrazer")
    fake.environment["NAGA_CONTROL_INSTALL_OPENRAZER"] = "0"
    result, commands = fake.run(*args, script=script)
    assert result.returncode == 0, result.stderr
    assert "hard skip" in result.stdout
    assert not any(c[0] in ("dpkg-query", "rpm") for c in commands)
    assert not any(c[0] == "system-python3" and "PathFinder" in " ".join(c) for c in commands)
    assert not any(
        "install_openrazer_native.sh" in i for c in commands for i in c if c[0] == "curl"
    )
    assert_private_cleanup(fake)


def test_native_explicit_selects_family_before_stop(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    write_os(fake, FEDORA_OS)
    fake.configure(installed={}, stamps={}, python_root=False, python_client=False)
    fake.configure(python_daemon=False, dpkg_installed={}, rpm_installed={})
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
    assert "family=fedora" in result.stdout
    assert any(c[0] == "rpm" and c[1] == "-qa" for c in commands)
    helpers = [c for c in commands if c[0] == "installer-helper"]
    assert helpers
    rpm_index = next(i for i, c in enumerate(commands) if c[0] == "rpm" and c[1] == "-qa")
    assert rpm_index < commands.index(helpers[0])
    assert ["pacman", "-Q"] not in commands
    assert_private_cleanup(fake)


def test_old_leap_python36_blocks_offer(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    _absent(fake, LEAP_OS)
    fake.configure(host_python="3.6")
    stage_native_helper_local(fake, script)
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "app-only install" in result.stdout
    assert "unknown or host not eligible" in result.stdout
    assert not any(c[0] == "installer-helper" for c in commands)
    assert_private_cleanup(fake)


@pytest.mark.parametrize("os_text", [RHEL_OS, SLES_OS, "ID=arch\n", "ID=unknown\n", ""])
def test_unsupported_ids_never_automate(tmp_path: Path, os_text: str) -> None:
    fake, script = offer_harness(tmp_path)
    write_os(fake, os_text)
    fake.configure(installed={}, stamps={}, python_root=False, python_client=False)
    fake.configure(python_daemon=False, dpkg_installed={}, rpm_installed={})
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "app-only install" in result.stdout
    assert not any(c[0] == "installer-helper" for c in commands)
    assert_private_cleanup(fake)


def test_native_partial_and_manual_present(tmp_path: Path) -> None:
    for setup in ("partial", "manual"):
        case = tmp_path / setup
        case.mkdir()
        fake, script = offer_harness(case)
        write_os(fake, UBUNTU_OS)
        if setup == "partial":
            fake.configure(dpkg_installed={"openrazer-daemon": "3.12.1-1"})
        else:
            fake.configure(dpkg_installed={})
            stub = fake.root / "bin/openrazer-daemon"
            stub.write_text('#!/usr/bin/env python3\nprint("MUST NOT EXECUTE")\n')
            stub.chmod(0o755)
        fake.configure(installed={}, stamps={}, python_root=False, python_client=False)
        fake.configure(python_daemon=False, rpm_installed={})
        result, commands = fake.run("--version", TAG, script=script)
        assert result.returncode == 0, result.stderr
        assert "leaving it unchanged" in result.stdout
        assert not any(c[0] == "installer-helper" for c in commands)
        assert not any(c[0] == "openrazer-daemon" for c in commands)
        assert_private_cleanup(fake)


@pytest.mark.parametrize("kind", ["dpkg", "rpm", "python"])
def test_native_malformed_unknown(tmp_path: Path, kind: str) -> None:
    fake, script = offer_harness(tmp_path)
    os_text = UBUNTU_OS if kind != "rpm" else FEDORA_OS
    _absent(fake, os_text)
    if kind == "dpkg":
        fake.configure(dpkg_malformed="bad-row-without-status")
    elif kind == "rpm":
        fake.configure(rpm_malformed="bad row with three columns here")
    else:
        fake.configure(offer_malformed="garbage")
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "unknown or host not eligible" in result.stdout or "app-only" in result.stdout
    assert not any(c[0] == "installer-helper" for c in commands)
    assert_private_cleanup(fake)


def test_local_helper_needs_no_api_query(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    _absent(fake, UBUNTU_OS)
    stage_native_helper_local(fake, script)
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n")
        result, commands = fake.run("--version", TAG, script=script, input_fd=slave)
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode == 0, result.stderr
    assert not any("api.github.com" in i for c in commands for i in c if c[0] == "curl")
    helpers = [c for c in commands if c[0] == "installer-helper"]
    assert helpers and "--code-ref" in helpers[0]
    assert_private_cleanup(fake)


def test_remote_helper_fetch_uses_sha_not_version(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    _absent(fake, UBUNTU_OS)
    stage_native_helper_remote(fake)
    fake.configure(naga_sha="b" * 40)
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n")
        result, commands = fake.run("--version", TAG, script=script, input_fd=slave)
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode == 0, result.stderr + result.stdout
    urls = [i for c in commands if c[0] == "curl" for i in c if "https:" in i]
    assert any("api.github.com" in u and "/commits/main" in u for u in urls)
    assert any(("b" * 40) + "/scripts/install_openrazer_native.sh" in u for u in urls)
    assert not any(TAG + "/scripts/install_openrazer_native.sh" in u for u in urls)
    helpers = [c for c in commands if c[0] == "installer-helper"]
    assert any("b" * 40 in c for c in helpers)
    assert_private_cleanup(fake)


@pytest.mark.parametrize("api_state", ["failure", "empty", "multiline"])
def test_api_errors_fail_before_stop(tmp_path: Path, api_state: str) -> None:
    fake, script = offer_harness(tmp_path)
    _absent(fake, UBUNTU_OS)
    stage_native_helper_remote(fake)
    if api_state == "failure":
        fake.configure(api_failure=1)
    elif api_state == "empty":
        fake.configure(api_malformed="")
    else:
        fake.configure(api_malformed=["abc", "def"])
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
    assert "installation not completed" in result.stderr
    assert not any(c[0] == "installer-helper" for c in commands)
    assert_private_cleanup(fake)


@pytest.mark.parametrize("bad_ref", ["../tag", "/absolute", "a..b", "a//b"])
def test_invalid_bootstrap_ref_fails_before_stop(tmp_path: Path, bad_ref: str) -> None:
    fake, script = offer_harness(tmp_path)
    _absent(fake, UBUNTU_OS)
    stage_native_helper_remote(fake)
    fake.environment["NAGA_CONTROL_BOOTSTRAP_REF"] = bad_ref
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
    assert "invalid code ref" in result.stderr
    assert not any(c[0] == "installer-helper" for c in commands)
    assert_private_cleanup(fake)


def test_explicit_unsupported_fails_before_stop(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    write_os(fake, RHEL_OS)
    fake.configure(installed={}, stamps={}, python_root=False, python_client=False)
    fake.configure(python_daemon=False, dpkg_installed={}, rpm_installed={})
    result, commands = fake.run(
        "--version", TAG, "--install-openrazer", "--restart-service", script=script
    )
    assert result.returncode != 0
    assert "unsupported on this host" in result.stderr
    assert not any(c[0] == "installer-helper" for c in commands)
    assert_private_cleanup(fake)
