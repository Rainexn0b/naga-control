"""Closed-PATH ldconfig discovery keeps FUSE/session preflight fail-closed."""

from pathlib import Path

import pytest

from tests.installer_app_fakes import HELPER_OK, installed_image, mutations, seed_previous, stamp
from tests.installer_ldconfig_fakes import (
    assert_cache_query,
    home_snapshot,
    ldconfig_harness,
    write_ldconfig,
)
from tests.openrazer_installer_fakes import TAG, InstallerHarness


def _assert_preflight_failure(
    fake: InstallerHarness, script: Path, message: str
) -> list[list[str]]:
    before_home = home_snapshot(fake)
    before_state = (fake.root / "state.json").read_bytes()
    result, commands = fake.run(
        "--version", TAG, "--install-openrazer", "--restart-service", script=script
    )
    assert result.returncode == 1, result.stderr
    assert message in result.stderr
    assert mutations(commands) == []
    assert {command[0] for command in commands} <= {
        "id",
        "uname",
        "systemctl",
        "busctl",
        "ldconfig",
        "stat",
    }
    assert all(
        command == ["systemctl", "--user", "show", "--property=Version", "--value"]
        for command in commands
        if command[0] == "systemctl"
    )
    assert home_snapshot(fake) == before_home
    assert (fake.root / "state.json").read_bytes() == before_state
    assert not (fake.root / "home/.local/share/naga-control/install.lock").exists()
    assert not list((fake.root / "temporary").iterdir())
    assert "app installed;" not in result.stdout and "installation staged:" not in result.stdout
    return commands


def _candidate(fake: InstallerHarness, path: Path, kind: str) -> None:
    if kind == "directory":
        path.mkdir(parents=True)
    elif kind != "absent":
        write_ldconfig(fake, path)
        if kind == "nonexecutable":
            path.chmod(0o644)


def test_path_ldconfig_is_preferred_over_both_fixed_paths(tmp_path: Path) -> None:
    fake, script, fixed = ldconfig_harness(tmp_path)
    preferred = fake.root / "bin/ldconfig"
    write_ldconfig(fake, preferred)
    for fallback in fixed:
        write_ldconfig(fake, fallback, status=99)
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert_cache_query(fake, preferred, commands)
    assert installed_image(fake).exists() and stamp(fake).read_text() == TAG + "\n"
    assert not any(
        command[0] in {"python", "python3", "system-python3", "pacman", "installer-helper"}
        for command in commands
    )


@pytest.mark.parametrize("path_kind", ["absent", "nonexecutable", "directory"])
@pytest.mark.parametrize(
    "first,second,winner",
    [
        ("executable", "executable", 0),
        ("executable", "absent", 0),
        ("absent", "executable", 1),
        ("nonexecutable", "executable", 1),
        ("directory", "executable", 1),
    ],
)
def test_fixed_paths_supply_unusable_path_ldconfig_in_priority_order(
    tmp_path: Path, path_kind: str, first: str, second: str, winner: int
) -> None:
    fake, script, fixed = ldconfig_harness(tmp_path)
    preferred = fake.root / "bin/ldconfig"
    preferred.unlink()
    _candidate(fake, preferred, path_kind)
    _candidate(fake, fixed[0], first)
    _candidate(fake, fixed[1], second)
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert_cache_query(fake, fixed[winner], commands)
    assert installed_image(fake).exists()


@pytest.mark.parametrize("kind", ["absent", "nonexecutable", "directory"])
def test_no_usable_ldconfig_fails_before_any_mutation(tmp_path: Path, kind: str) -> None:
    fake, script, fixed = ldconfig_harness(tmp_path, helper=HELPER_OK)
    preferred = fake.root / "bin/ldconfig"
    preferred.unlink()
    for path in (preferred, *fixed):
        _candidate(fake, path, kind)
    fake.configure(service_state="active")
    _assert_preflight_failure(fake, script, "ldconfig is required for FUSE2 library discovery")
    assert not (fake.root / "ldconfig-query").exists()


@pytest.mark.parametrize("location", ["path", "first", "second"])
@pytest.mark.parametrize("partial_output", [False, True])
def test_failed_cache_query_rejects_even_valid_partial_output(
    tmp_path: Path, location: str, partial_output: bool
) -> None:
    fake, script, fixed = ldconfig_harness(tmp_path, helper=HELPER_OK)
    preferred = fake.root / "bin/ldconfig"
    preferred.unlink()
    selected = {"path": preferred, "first": fixed[0], "second": fixed[1]}[location]
    if location == "first":
        write_ldconfig(fake, fixed[1])
    write_ldconfig(fake, selected, output=None if partial_output else "", status=2)
    seed_previous(fake)
    commands = _assert_preflight_failure(fake, script, "ldconfig -p failed; cannot verify FUSE2")
    assert_cache_query(fake, selected, commands)


@pytest.mark.parametrize("location", ["path", "first", "second"])
@pytest.mark.parametrize(
    "problem", ["i386", "libfuse.so.3", "libfuse.so.2.extra", "unreadable", "missing"]
)
def test_cache_success_still_requires_exact_readable_x86_64_fuse2(
    tmp_path: Path, location: str, problem: str
) -> None:
    fake, script, fixed = ldconfig_harness(tmp_path, helper=HELPER_OK)
    preferred = fake.root / "bin/ldconfig"
    preferred.unlink()
    selected = {"path": preferred, "first": fixed[0], "second": fixed[1]}[location]
    library = fake.root / "libfuse.so.2"
    soname = problem if problem.startswith("libfuse") else "libfuse.so.2"
    arch = "i386" if problem == "i386" else "x86-64"
    output = "" if problem == "missing" else f"{soname} (libc6,{arch}) => {library}\n"
    write_ldconfig(fake, selected, output=output)
    if problem == "unreadable":
        library.chmod(0o000)
    fake.configure(service_state="active")
    commands = _assert_preflight_failure(fake, script, "FUSE2 library missing")
    assert_cache_query(fake, selected, commands)


@pytest.mark.parametrize(
    "problem,message",
    [
        ("uid", "run as your desktop user, not root"),
        ("os", "Linux x86_64"),
        ("arch", "Linux x86_64"),
        ("systemd_failure", "user systemd unavailable"),
        ("bus_failure", "session D-Bus unavailable"),
        ("fuse_runtime_missing", "FUSE runtime unavailable"),
        ("kernel", "kernel FUSE support unavailable"),
        ("extraction", "unset APPIMAGE_EXTRACT_AND_RUN"),
    ],
)
def test_fixed_ldconfig_does_not_bypass_other_preflight_gates(
    tmp_path: Path, problem: str, message: str
) -> None:
    fake, script, fixed = ldconfig_harness(tmp_path, helper=HELPER_OK)
    (fake.root / "bin/ldconfig").unlink()
    write_ldconfig(fake, fixed[0])
    fake.configure(service_state="active")
    if problem == "kernel":
        (fake.root / "filesystems").write_text("nodev\tfusectl\n")
    elif problem == "extraction":
        fake.environment["APPIMAGE_EXTRACT_AND_RUN"] = "1"
    else:
        value = {"uid": "0", "os": "Darwin", "arch": "aarch64"}.get(problem, 1)
        fake.configure(**{problem: value})
    commands = _assert_preflight_failure(fake, script, message)
    if problem in {"fuse_runtime_missing", "kernel"}:
        assert_cache_query(fake, fixed[0], commands)
    else:
        assert not (fake.root / "ldconfig-query").exists()
