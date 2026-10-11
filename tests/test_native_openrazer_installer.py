"""Native first-install positives and consent boundaries."""

import os
import pty
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.native_openrazer_installer_fakes import (
    DEBIAN_OS,
    FEDORA_OS,
    LEAP_OS,
    TW_OS,
    InstallerHarness,
    harness,
    mutations,
    write_os,
)


def _debian(fake: InstallerHarness) -> None:
    write_os(fake, DEBIAN_OS)


def _fedora(fake: InstallerHarness) -> None:
    write_os(fake, FEDORA_OS)
    fake.configure(kernel="6.10.5-1.fc42.x86_64")
    build = fake.root / "modules/6.10.5-1.fc42.x86_64/build"
    build.mkdir(parents=True, exist_ok=True)
    (build / "Makefile").touch()
    (build / ".config").write_text("CONFIG_CC_IS_CLANG=n\n")


def _leap(fake: InstallerHarness) -> None:
    write_os(fake, LEAP_OS)
    fake.configure(kernel="6.10.5-1-default", kernel_evr="6.10.5-1.1")
    build = fake.root / "modules/6.10.5-1-default/build"
    build.mkdir(parents=True, exist_ok=True)
    (build / "Makefile").touch()
    (build / ".config").write_text("CONFIG_CC_IS_CLANG=n\n")


def _run_yes_with_prereq(
    fake: InstallerHarness, *args: str
) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n")
        return fake.run(*args, input_fd=slave)
    finally:
        os.close(master)
        os.close(slave)


@pytest.mark.parametrize(
    "family,setup", [("debian", _debian), ("fedora", _fedora), ("opensuse", _leap)]
)
def test_positives_build_and_install_one_transaction(
    tmp_path: Path, family: str, setup: Callable[[InstallerHarness], None]
) -> None:
    fake = harness(tmp_path)
    setup(fake)
    fake.configure(groups="users openrazer")
    result, commands = _run_yes_with_prereq(fake, "--family", family, "--yes")
    assert result.returncode == 0, result.stderr
    assert "Native packages installed; activation DEFERRED" in result.stdout
    assert "Reboot/re-login" in result.stdout
    if family == "debian":
        tx = next(
            c
            for c in commands
            if c[:2] == ["sudo", "apt-get"] and any(p.endswith(".deb") for p in c)
        )
        assert tx[2] == "install"
        assert len([p for p in tx[3:] if p.endswith(".deb")]) == 3
        assert not any(f in tx for f in ("-y", "--noconfirm", "--non-interactive"))
    elif family == "fedora":
        tx = next(
            c for c in commands if c[:2] == ["sudo", "dnf"] and any(p.endswith(".rpm") for p in c)
        )
        assert tx[2] == "install"
        assert len([p for p in tx[3:] if p.endswith(".rpm")]) == 3
    else:
        tx = next(
            c
            for c in commands
            if c[:2] == ["sudo", "zypper"] and any(p.endswith(".rpm") for p in c)
        )
        assert tx[2:4] == ["install", "--allow-unsigned-rpm"]
        assert len([p for p in tx[4:] if p.endswith(".rpm")]) == 3
    assert ["systemctl", "--user", "daemon-reload"] in commands
    assert ["systemctl", "--user", "enable", "openrazer-daemon.service"] in commands
    assert not any("--now" in c or "restart" in c for c in commands)


def test_headers_omitted_when_tree_present(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.configure(groups="users openrazer")
    result, commands = _run_yes_with_prereq(fake, "--family", "debian", "--yes")
    assert result.returncode == 0, result.stderr
    prereq = next(
        c
        for c in commands
        if c[:2] == ["sudo", "apt-get"] and not any(p.endswith(".deb") for p in c)
    )
    assert not any("linux-headers-" in p for p in prereq)


def test_headers_included_when_tree_missing(tmp_path: Path) -> None:
    import shutil

    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.configure(groups="users openrazer")
    shutil.rmtree(fake.root / "modules/6.8.0-52-generic")
    result, commands = _run_yes_with_prereq(fake, "--family", "debian", "--yes")
    assert result.returncode != 0
    prereq = next(
        c
        for c in commands
        if c[:2] == ["sudo", "apt-get"] and not any(p.endswith(".deb") for p in c)
    )
    assert any("linux-headers-6.8.0-52-generic" in p for p in prereq)


def test_wrapper_argv_regression_with_minimal_builder(tmp_path: Path) -> None:
    import re
    import subprocess

    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts/install_openrazer_native.sh").read_text()
    match = re.search(
        r"/usr/bin/python3 -I -B -c 'import runpy,sys; .*?run_module\(\"buildpython\.openrazer_native\".*?'",
        source,
    )
    assert match is not None
    code = match.group(0).split("-c '", 1)[1].rsplit("'", 1)[0]
    assert "del sys.argv[1]" in code
    code_root = tmp_path / "code-root"
    pkg = code_root / "buildpython/openrazer_native"
    pkg.mkdir(parents=True)
    (code_root / "buildpython/__init__.py").write_text("")
    (pkg / "__init__.py").write_text("")
    (pkg / "__main__.py").write_text(
        "import argparse,pathlib,sys\n"
        "p=argparse.ArgumentParser()\n"
        "p.add_argument('--family',required=True)\n"
        "p.add_argument('--source',required=True)\n"
        "p.add_argument('--output',required=True)\n"
        "p.add_argument('--pin',required=True)\n"
        "a=p.parse_args()\n"
        "pathlib.Path(a.output).mkdir(parents=True,exist_ok=True)\n"
        "pathlib.Path(a.output,'ok').write_text(a.family)\n"
    )
    src = tmp_path / "src"
    src.mkdir()
    out = tmp_path / "out"
    pin = tmp_path / "pin.conf"
    pin.write_text("pin\n")
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            code,
            str(code_root),
            "--family",
            "debian",
            "--source",
            str(src),
            "--output",
            str(out),
            "--pin",
            str(pin),
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (out / "ok").read_text() == "debian"


def test_tumbleweed_is_eligible(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, TW_OS)
    fake.configure(kernel="6.11.0-1-default", kernel_evr="6.11.0-1.1", groups="users openrazer")
    build = fake.root / "modules/6.11.0-1-default/build"
    build.mkdir(parents=True, exist_ok=True)
    (build / "Makefile").touch()
    (build / ".config").write_text("CONFIG_CC_IS_CLANG=n\n")
    result, commands = _run_yes_with_prereq(fake, "--family", "opensuse", "--yes")
    assert result.returncode == 0, result.stderr
    assert any(c[:2] == ["sudo", "zypper"] for c in commands)


@pytest.mark.parametrize("arguments", [(), ("--check",), ("--check", "--yes")])
def test_check_and_default_are_read_only(tmp_path: Path, arguments: tuple[str, ...]) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    result, commands = fake.run("--family", "debian", *arguments)
    assert result.returncode == 0, result.stderr
    assert "ABSENT" in result.stdout
    assert "Host import discoverability" in result.stdout
    assert not any(c[0] in {"curl", "sudo", "git"} for c in commands)


def test_preflight_is_read_only_no_tmp_lock(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    result, commands = fake.run("--family", "debian", "--preflight")
    assert result.returncode == 0, result.stderr
    assert "Prerequisite plan" in result.stdout
    assert "Read-only native preflight passed" in result.stdout
    assert not any(c[0] in {"curl", "sudo", "git"} for c in commands)
    assert not list((fake.root / "temporary").iterdir())
    assert not (fake.root / "home/.local/share/naga-control/install.lock").exists()


def test_env_zero_hard_skips_everything(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.environment["NAGA_CONTROL_INSTALL_OPENRAZER"] = "0"
    result, commands = fake.run("--family", "debian", "--yes")
    assert result.returncode == 0
    assert "hard skip" in result.stdout
    assert commands == []


@pytest.mark.parametrize("value", ["", "true", "2"])
def test_invalid_env_rejected(tmp_path: Path, value: str) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.environment["NAGA_CONTROL_INSTALL_OPENRAZER"] = value
    result, commands = fake.run("--family", "debian")
    assert result.returncode != 0
    assert "must be 0, 1, or unset" in result.stderr
    assert commands == []


def test_check_overrides_env_opt_in(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.environment["NAGA_CONTROL_INSTALL_OPENRAZER"] = "1"
    result, commands = fake.run("--family", "debian", "--check")
    assert result.returncode == 0, result.stderr
    assert not any(c[0] in {"curl", "sudo"} for c in commands)


def test_yes_still_requires_prereq_terminal(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    result, commands = fake.run("--family", "debian", "--yes")
    assert result.returncode != 0
    assert "prerequisite confirmation requires a terminal" in result.stderr
    assert not any(c[0] == "sudo" for c in commands)


def test_summary_and_prereq_two_confirms(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.configure(groups="users openrazer")
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\ny\n")
        result, commands = fake.run("--family", "debian", "--install", input_fd=slave)
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode == 0, result.stderr
    assert any(c[0] == "sudo" for c in commands)


def test_prereq_decline_stops_before_sudo(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    master, slave = pty.openpty()
    try:
        os.write(master, b"n\n")
        result, commands = fake.run("--family", "debian", "--yes", input_fd=slave)
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode != 0
    assert "declined" in result.stderr.lower()
    assert mutations(commands) == []


def test_group_flag_uses_actual_user(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    result, commands = _run_yes_with_prereq(
        fake, "--family", "debian", "--yes", "--add-openrazer-group"
    )
    assert result.returncode == 0, result.stderr
    assert ["sudo", "usermod", "-aG", "openrazer", "desktop-user"] in commands
    assert "wrong-inherited-user" not in result.stdout


def test_debian_prereq_uses_concrete_dbus_user_session(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.configure(groups="users openrazer")
    result, commands = _run_yes_with_prereq(fake, "--family", "debian", "--yes")
    assert result.returncode == 0, result.stderr
    prereq = next(
        c
        for c in commands
        if c[:2] == ["sudo", "apt-get"] and not any(p.endswith(".deb") for p in c)
    )
    assert "dbus-user-session" in prereq
    assert "dbus-session-bus" not in prereq
    assert "dbus-user-session" in result.stdout
