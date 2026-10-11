"""Native validation rejects untrusted outputs before privileged install."""

import os
import pty
import subprocess
from pathlib import Path

import pytest

from tests.native_openrazer_installer_fakes import (
    DEBIAN_OS,
    InstallerHarness,
    harness,
    write_os,
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


def _no_cohort_sudo(commands: list[list[str]]) -> bool:
    for c in commands:
        if c[0] == "sudo" and any(p.endswith((".deb", ".rpm")) for p in c):
            return False
    return True


def test_prereq_failure_blocks_build_and_activation(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.configure(prereq_failure=1)
    result, commands = _yes_run(fake, "--family", "debian", "--yes")
    assert result.returncode != 0
    assert "prerequisite install failed" in result.stderr
    assert _no_cohort_sudo(commands)
    assert "Native packages installed; activation DEFERRED" not in result.stdout
    assert [p for p in (fake.root / "temporary").iterdir() if p.is_dir()] == []


def test_builder_failure_blocks_package_install(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.configure(builder_fail=1)
    result, commands = _yes_run(fake, "--family", "debian", "--yes")
    assert result.returncode != 0
    assert "native local build failed" in result.stderr
    assert _no_cohort_sudo(commands)


@pytest.mark.parametrize(
    "bad",
    [
        "missing-role",
        "mixed-python",
        "extra-file",
        "bad-digest",
        "bad-manifest-row",
        "bad-schema",
        "schema-true",
        "foreign-minor",
        "wrong-family",
        "wrong-commit",
        "extra-keys",
        "duplicate-keys",
        "role-swap",
        "missing-newline",
        "symlink",
        "hardlink",
        "sidecar-symlink",
        "json-symlink",
    ],
)
def test_invalid_build_outputs_block_cohort_sudo(tmp_path: Path, bad: str) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.configure(builder_bad=bad)
    result, commands = _yes_run(fake, "--family", "debian", "--yes")
    assert result.returncode != 0, result.stderr
    assert "invalid native build outputs" in result.stderr
    assert _no_cohort_sudo(commands)
    assert "Native packages installed; activation DEFERRED" not in result.stdout


def test_future_minor_is_accepted(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.configure(host_python="3.15", builder_bad="future-minor")
    result, _ = _yes_run(fake, "--family", "debian", "--yes")
    assert result.returncode == 0, result.stderr


def test_foreign_owner_blocks_cohort_sudo(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.configure(foreign_owner=1)
    result, commands = _yes_run(fake, "--family", "debian", "--yes")
    assert result.returncode != 0
    assert "invalid native build outputs" in result.stderr
    assert _no_cohort_sudo(commands)


def test_source_sha_mismatch_blocks_cohort_sudo(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.configure(git_head="b" * 40)
    result, commands = _yes_run(fake, "--family", "debian", "--yes")
    assert result.returncode != 0
    assert "HEAD mismatch" in result.stderr
    assert _no_cohort_sudo(commands)


def test_dirty_checkout_blocks_build(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.configure(git_dirty=1)
    result, commands = _yes_run(fake, "--family", "debian", "--yes")
    assert result.returncode != 0
    assert "not clean" in result.stderr
    assert _no_cohort_sudo(commands)


def test_dead_branch_fetch_fails(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.configure(git_dead_branch=1)
    result, commands = _yes_run(fake, "--family", "debian", "--yes")
    assert result.returncode != 0
    assert _no_cohort_sudo(commands)


@pytest.mark.parametrize(
    "kind", ["bad-pin", "not-archive", "wrong-root", "dotpath", "link", "missing-native"]
)
def test_bad_code_archive_blocks_build(tmp_path: Path, kind: str) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.configure(code_tar=kind)
    result, commands = _yes_run(fake, "--family", "debian", "--yes")
    assert result.returncode != 0
    assert _no_cohort_sudo(commands)


def test_bad_naga_sha_blocks_build(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.configure(naga_sha_text="not-a-sha\n")
    result, commands = _yes_run(fake, "--family", "debian", "--yes")
    assert result.returncode != 0
    assert _no_cohort_sudo(commands)


def test_package_install_failure_keeps_activation_pending(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.configure(pkg_failure=1)
    result, commands = _yes_run(fake, "--family", "debian", "--yes")
    assert result.returncode != 0
    assert "native package install failed" in result.stderr
    assert "Native packages installed; activation DEFERRED" not in result.stdout
    assert not any(
        c == ["systemctl", "--user", "enable", "openrazer-daemon.service"] for c in commands
    )


@pytest.mark.parametrize("failure", ["group", "unit"])
def test_group_and_unit_failures_have_no_activation(tmp_path: Path, failure: str) -> None:
    import os as _os
    import pty as _pty

    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    if failure == "group":
        fake.configure(group_failure=1, groups="users")
        master, slave = _pty.openpty()
        try:
            _os.write(master, b"y\n")
            result, commands = fake.run(
                "--family", "debian", "--yes", "--add-openrazer-group", input_fd=slave
            )
        finally:
            _os.close(master)
            _os.close(slave)
        assert result.returncode != 0
        assert "group addition failed" in result.stderr
    else:
        fake.configure(unit_failure="enable")
        result, commands = _yes_run(fake, "--family", "debian", "--yes")
        assert result.returncode != 0
        assert "daemon enable failed" in result.stderr
    assert "Native packages installed; activation DEFERRED" not in result.stdout
    assert not any("--now" in c or "restart" in c for c in commands)


def test_suse_unknown_flavor_blocks_without_repo_guess(tmp_path: Path) -> None:
    from tests.native_openrazer_installer_fakes import LEAP_OS

    fake = harness(tmp_path)
    write_os(fake, LEAP_OS)
    fake.configure(kernel="6.10.5-1-custom", whatprovides_fail=1, groups="users openrazer")
    result, commands = fake.run("--family", "opensuse", "--preflight")
    assert result.returncode != 0
    assert "manual headers required" in result.stderr
    assert not any(c[0] == "sudo" for c in commands)


def test_failure_cleans_private_tmp_only(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    profile = fake.root / "home/.config/naga-control/profiles.toml"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text("profile = true\n")
    fake.configure(builder_fail=1)
    result, _ = _yes_run(fake, "--family", "debian", "--yes")
    assert result.returncode != 0
    assert profile.read_text() == "profile = true\n"
    assert not list((fake.root / "temporary").iterdir())


def test_prereq_return_two_reports_partial_state(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    profile = fake.root / "home/.config/naga-control/profiles.toml"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text("profile = true\n")
    fake.configure(prereq_failure=2)
    result, commands = _yes_run(fake, "--family", "debian", "--yes")
    assert result.returncode != 0
    assert "possible partial prereq" in result.stderr
    assert "activation pending" in result.stderr
    assert "Native packages installed; activation DEFERRED" not in result.stdout
    assert _no_cohort_sudo(commands)
    assert not any(
        c == ["systemctl", "--user", "enable", "openrazer-daemon.service"] for c in commands
    )
    assert profile.read_text() == "profile = true\n"
    assert not list((fake.root / "temporary").iterdir())


def test_sigterm_during_prereq_reports_partial_state(tmp_path: Path) -> None:
    import json
    import signal
    import subprocess
    import time

    fake = harness(tmp_path)
    write_os(fake, DEBIAN_OS)
    fake.configure(groups="users openrazer", prereq_sleep=10)
    profile = fake.root / "home/.config/naga-control/profiles.toml"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text("profile = true\n")
    script = fake.root / "install_openrazer_native.sh"
    master, slave = pty.openpty()
    try:
        proc = subprocess.Popen(
            ["/bin/bash", str(script), "--family", "debian", "--yes"],
            env=fake.environment,
            stdin=slave,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        os.close(slave)
        slave = -1
        os.write(master, b"y\n")
        deadline = time.time() + 15
        started = False
        while time.time() < deadline:
            log = fake.root / "commands.jsonl"
            if log.exists():
                for line in log.read_text().splitlines():
                    entry = json.loads(line)
                    if entry[:2] == ["sudo", "apt-get"]:
                        started = True
                        break
            if started or proc.poll() is not None:
                break
            time.sleep(0.05)
        assert started, "prereq transaction never started"
        proc.send_signal(signal.SIGTERM)
        try:
            _, stderr = proc.communicate(timeout=20)
        except subprocess.TimeoutExpired as err:
            proc.kill()
            raise AssertionError("helper did not exit after SIGTERM") from err
    finally:
        if slave != -1:
            os.close(slave)
        os.close(master)
    assert proc.returncode == 143
    assert proc.returncode == 143
    assert "possible partial prereq" in stderr
    assert "activation pending" in stderr
    assert profile.read_text() == "profile = true\n"
    assert not list((fake.root / "temporary").iterdir())
    log = fake.root / "commands.jsonl"
    commands = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    assert _no_cohort_sudo(commands)
    assert not any(
        c == ["systemctl", "--user", "enable", "openrazer-daemon.service"] for c in commands
    )
