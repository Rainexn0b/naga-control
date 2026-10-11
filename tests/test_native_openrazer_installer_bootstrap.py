"""Native bootstrap, identity, inventory, and lock boundaries."""

import os
import pty
import subprocess
from pathlib import Path

import pytest

from tests.native_openrazer_installer_fakes import (
    DEBIAN_OS,
    FEDORA_OS,
    InstallerHarness,
    harness,
    write_os,
    write_vendor,
)


def _yes_run(
    fake: InstallerHarness, *args: str
) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    fake.configure(groups="users openrazer")
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n")
        return fake.run(*args, input_fd=slave)
    finally:
        os.close(master)
        os.close(slave)


def test_family_must_match_named_os(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    result, commands = fake.run("--family", "fedora", "--yes")
    assert result.returncode != 0
    assert "unsupported host" in result.stderr
    assert not any(c[0] == "sudo" for c in commands)


def test_derivative_has_no_automated_helper(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, 'NAME="Mint"\nID=linuxmint\nID_LIKE=ubuntu\n')
    result, commands = fake.run("--family", "debian", "--yes")
    assert result.returncode != 0
    assert "unsupported host" in result.stderr
    assert not any(c[0] == "sudo" for c in commands)


def test_arch_id_is_not_native_eligible(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, 'NAME="Arch Linux"\nID=arch\n')
    result, commands = fake.run("--family", "debian", "--yes")
    assert result.returncode != 0
    assert not any(c[0] == "sudo" for c in commands)


@pytest.mark.parametrize(
    "text",
    [
        "ID=ubuntu\nID=debian\n",
        "ID=ubuntu\nID_LIKE=debian\nID_LIKE=ubuntu\n",
        'ID="ubuntu\n',
        "ID=ubuntu\x01\n",
        "ID=Ubuntu\n",
        "X" * 4097 + "\nID=ubuntu\n",
    ],
)
def test_malformed_os_release_refuses_install(tmp_path: Path, text: str) -> None:
    fake = harness(tmp_path)
    write_os(fake, text)
    result, commands = fake.run("--family", "debian", "--yes")
    assert result.returncode != 0
    assert not any(c[0] == "sudo" for c in commands)


def test_unicode_name_crlf_and_nolf_are_ignored(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, 'NAME="\u00dcbuntu"\nID=ubuntu\r\nID_LIKE=debian')
    result, _ = fake.run("--family", "debian", "--preflight")
    assert result.returncode == 0, result.stderr


def test_over_64kib_multibyte_is_unknown(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, ("\u00e9" * 40000).encode() + b"\nID=ubuntu\n")
    result, commands = fake.run("--family", "debian", "--yes")
    assert result.returncode != 0
    assert not any(c[0] == "sudo" for c in commands)


def test_over_4096_byte_unicode_line_refuses(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, "ID=" + "\u00e9" * 3000 + "\n")
    result, commands = fake.run("--family", "debian", "--yes")
    assert result.returncode != 0
    assert not any(c[0] == "sudo" for c in commands)


def test_evil_etc_never_falls_back_to_vendor(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, "ID=ubuntu\nID=debian\n")
    write_vendor(fake, FEDORA_OS)
    result, commands = fake.run("--family", "fedora", "--yes")
    assert result.returncode != 0
    assert not any(c[0] == "sudo" for c in commands)


def test_vendor_fallback_when_etc_absent(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    (fake.root / "os-release").unlink()
    write_vendor(fake, FEDORA_OS)
    fake.configure(kernel="6.10.5-1.fc42.x86_64")
    build = fake.root / "modules/6.10.5-1.fc42.x86_64/build"
    build.mkdir(parents=True, exist_ok=True)
    (build / "Makefile").touch()
    (build / ".config").write_text("CONFIG_CC_IS_CLANG=n\n")
    result, _ = fake.run("--family", "fedora", "--preflight")
    assert result.returncode == 0, result.stderr


def test_missing_manager_blocks_eligibility(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    (Path(fake.environment["PATH"]) / "dpkg-query").unlink()
    result, commands = fake.run("--family", "debian", "--yes")
    assert result.returncode != 0
    assert ("manager capability missing" in result.stderr) or ("refused" in result.stderr)
    assert not any(c[0] == "sudo" for c in commands)


@pytest.mark.parametrize(
    "installed",
    [
        {"openrazer-driver-dkms-local": "3.12.1.pr2904.fix2-1"},
        {"openrazer-daemon": "3.12.1-1"},
        {"openrazer-meta": "3.12.1-1"},
        {"razer-kernel-modules": "1.0"},
    ],
)
def test_existing_packages_refuse_replacement(tmp_path: Path, installed: dict[str, str]) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.configure(installed=installed)
    result, _ = fake.run("--family", "debian", "--check")
    assert result.returncode == 0
    assert "UNVERIFIED" in result.stdout
    result, commands = fake.run("--family", "debian", "--yes")
    assert result.returncode != 0
    assert "refused" in result.stderr
    assert not any(c[0] == "sudo" for c in commands)


def test_query_no_space_is_unknown_not_absent(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.configure(query_malformed="no-space")
    result, _ = fake.run("--family", "debian", "--check")
    assert result.returncode == 0
    assert "UNVERIFIED" in result.stdout
    assert "ABSENT" not in result.stdout


def test_manual_root_package_preserved(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.configure(python_root=True, python_client=False, python_daemon=False)
    result, commands = fake.run("--family", "debian", "--yes")
    assert result.returncode != 0
    assert not any(c[0] == "sudo" for c in commands)


def test_manual_imports_preserved_when_db_empty(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.configure(python_client=True)
    result, commands = fake.run("--family", "debian", "--yes")
    assert result.returncode != 0
    assert "refused" in result.stderr or "manual" in result.stderr.lower()
    assert not any(c[0] == "sudo" for c in commands)


@pytest.mark.parametrize("field", ["python_discover_error", "python_malformed"])
def test_broken_python_probe_is_unknown(tmp_path: Path, field: str) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    if field == "python_discover_error":
        fake.configure(python_discover_error=1)
    else:
        fake.configure(python_malformed="OPENRAZER-PROBE bogus")
    result, _ = fake.run("--family", "debian", "--check")
    assert result.returncode == 0
    assert "UNVERIFIED" in result.stdout
    assert "ABSENT" not in result.stdout


def test_daemon_command_preserved(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    (Path(fake.environment["PATH"]) / "openrazer-daemon").write_text("#!/bin/sh\n")
    (Path(fake.environment["PATH"]) / "openrazer-daemon").chmod(0o755)
    result, commands = fake.run("--family", "debian", "--yes")
    assert result.returncode != 0
    assert not any(c[0] == "sudo" for c in commands)


def test_unknown_query_refuses_without_absence_claim(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.configure(query_fail=1)
    result, commands = fake.run("--family", "debian", "--yes")
    assert result.returncode != 0
    assert not any(c[0] == "sudo" for c in commands)


def test_old_python_blocks_without_replacement(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.configure(host_python="3.9")
    result, commands = fake.run("--family", "debian", "--yes")
    assert result.returncode != 0
    assert "3.10" in result.stderr
    assert not any(c[0] == "sudo" for c in commands)


def test_root_is_refused(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.configure(uid="0")
    result, commands = fake.run("--family", "debian", "--yes")
    assert result.returncode != 0
    assert "not root" in result.stderr
    assert not any(c[0] == "sudo" for c in commands)


def test_nonstandard_uid_is_allowed(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.configure(uid="1234", groups="users openrazer")
    master_result, _ = fake.run("--family", "debian", "--preflight")
    assert master_result.returncode == 0, master_result.stderr


def test_venv_does_not_change_system_python(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.configure(host_python="3.12", venv_python="3.10")
    fake.environment["VIRTUAL_ENV"] = str(tmp_path / "venv")
    fake.environment["PYTHONPATH"] = "/tmp/bogus"
    result, commands = _yes_run(fake, "--family", "debian", "--yes")
    assert result.returncode == 0, result.stderr
    assert not any(c[0] in {"python", "python3"} for c in commands)
    assert any(c[0] == "system-python3" for c in commands)


def test_version_tag_validated_no_release_assets(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    result, _ = fake.run("--family", "debian", "--yes", "--version", "bad tag!")
    assert result.returncode != 0
    assert "invalid release tag" in result.stderr
    fake2 = harness(tmp_path / "second")
    write_os(fake2, DEBIAN_OS)
    result, commands = _yes_run(fake2, "--family", "debian", "--yes", "--version", "v0.4.0")
    assert result.returncode == 0, result.stderr
    assert not any("releases/download" in i for c in commands for i in c)


def test_code_ref_validation(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    for bad in ["../bad", "/abs", "bad..ref", "bad;echo"]:
        result, _ = fake.run("--family", "debian", "--yes", "--code-ref", bad)
        assert result.returncode != 0, bad


def test_concurrent_lock_fails_before_mutation(tmp_path: Path) -> None:
    import fcntl

    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.configure(groups="users openrazer")
    lock_dir = fake.root / "home/.local/share/naga-control"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock = lock_dir / "install.lock"
    lock.touch()
    holder = os.open(str(lock), os.O_RDWR)
    try:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        master, slave = pty.openpty()
        try:
            os.write(master, b"y\ny\n")
            result, commands = fake.run("--family", "debian", "--install", input_fd=slave)
        finally:
            os.close(master)
            os.close(slave)
        assert result.returncode != 0
        assert "another Naga installer is running" in result.stderr
        assert not any(c[0] == "sudo" for c in commands)
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN)
        os.close(holder)


def test_suse_preflight_blocks_unknown_flavor(tmp_path: Path) -> None:
    from tests.native_openrazer_installer_fakes import LEAP_OS

    fake = harness(tmp_path)
    write_os(fake, LEAP_OS)
    fake.configure(kernel="6.10.5-1-custom")
    build = fake.root / "modules/6.10.5-1-custom/build"
    if build.exists():
        import shutil

        shutil.rmtree(build.parent)
    result, _ = fake.run("--family", "opensuse", "--preflight")
    assert result.returncode != 0
    assert "manual headers required" in result.stderr


def test_suse_prereq_uses_exact_evr_no_repo_add(tmp_path: Path) -> None:
    from tests.native_openrazer_installer_fakes import LEAP_OS

    fake = harness(tmp_path)
    write_os(fake, LEAP_OS)
    fake.configure(kernel="6.10.5-1-default", kernel_evr="6.10.5-1.1")
    build = fake.root / "modules/6.10.5-1-default/build"
    build.mkdir(parents=True, exist_ok=True)
    (build / "Makefile").touch()
    (build / ".config").write_text("CONFIG_CC_IS_CLANG=n\n")
    result, commands = _yes_run(fake, "--family", "opensuse", "--yes")
    assert result.returncode == 0, result.stderr
    assert not any("addrepo" in c or "refresh" in c for c in commands)
    # Exact EVR is queried read-only before mutation when headers are missing.
    fake2 = harness(tmp_path / "evr")
    write_os(fake2, LEAP_OS)
    fake2.configure(kernel="6.10.5-1-default", kernel_evr="6.10.5-1.1")
    result, _ = fake2.run("--family", "opensuse", "--preflight")
    assert result.returncode == 0, result.stderr
