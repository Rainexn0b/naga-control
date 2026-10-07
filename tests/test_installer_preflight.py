"""Read-only environment/tool/build preflight with no actual device operations."""

import json
from pathlib import Path

import pytest

from tests.installer_app_fakes import (
    PREVIOUS_TAG,
    USER_FILES,
    app_harness,
    assert_private_cleanup,
    installed_image,
    mutations,
    seed_previous,
    stamp,
)
from tests.openrazer_installer_fakes import TAG, harness, operation_name


@pytest.mark.parametrize(
    "changes,message",
    [
        ({"uid": "0"}, "run as your desktop user, not root"),
        ({"os": "Darwin"}, "Linux x86_64"),
        ({"arch": "aarch64"}, "Linux x86_64"),
        ({"systemd_failure": 1}, "user systemd unavailable"),
        ({"bus_failure": 1}, "session D-Bus unavailable"),
        ({"fuse_library_missing": True}, "FUSE2 library missing"),
        ({"fuse_library_arch": "i386"}, "FUSE2 library missing"),
        ({"fuse_runtime_missing": True}, "FUSE runtime unavailable"),
    ],
)
def test_preflight_failure_has_no_installation_mutations(
    tmp_path: Path, changes: dict[str, object], message: str
) -> None:
    fake, script = app_harness(tmp_path)
    fake.configure(**changes)
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode != 0
    assert message in result.stderr
    assert mutations(commands) == []
    assert not installed_image(fake).exists()
    assert not stamp(fake).exists()
    assert not (fake.root / "home/.local").exists()
    assert not any(c[0] == "curl" for c in commands)


@pytest.mark.parametrize(
    "tool", ["curl", "busctl", "flock", "sha256sum", "sudo", "install", "udevadm"]
)
def test_missing_app_tools_fail_without_mutations(tmp_path: Path, tool: str) -> None:
    fake, script = app_harness(tmp_path)
    (fake.root / "bin" / tool).unlink()
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode != 0
    assert tool + " is required" in result.stderr
    assert mutations(commands) == []
    assert not (fake.root / "home/.local").exists()


@pytest.mark.parametrize(
    "relative",
    [
        ".local",
        ".local/bin/naga-control.AppImage",
        ".local/bin/naga-control",
        ".local/share/naga-control/installed-tag",
        ".local/share/naga-control/install.lock",
        ".config/systemd/user/naga-control.service",
    ],
)
def test_symlink_destinations_and_ancestors_never_followed(tmp_path: Path, relative: str) -> None:
    fake, script = app_harness(tmp_path)
    destination = fake.root / "home" / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    protected = fake.root / "protected"
    protected.write_text("keep me\n")
    destination.symlink_to(protected)
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode != 0
    assert "symlink installation destination/ancestor" in result.stderr
    assert protected.read_text() == "keep me\n"
    assert mutations(commands) == []
    assert not any(c[0] == "curl" for c in commands)


def test_unwritable_home_tree_is_rejected_read_only(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    local = fake.root / "home/.local"
    local.mkdir(mode=0o500)
    try:
        result, commands = fake.run("--version", TAG, script=script)
    finally:
        local.chmod(0o700)
    assert result.returncode != 0
    assert "not writable" in result.stderr
    assert mutations(commands) == []


@pytest.mark.parametrize("value", ["", "1", "2", "yes", "false", "00", " "])
@pytest.mark.parametrize("fuse_available", [False, True])
def test_managed_install_rejects_extraction_before_network_or_changes(
    tmp_path: Path, value: str, fuse_available: bool
) -> None:
    fake, script = app_harness(tmp_path)
    fake.configure(fuse_library_missing=not fuse_available, fuse_runtime_missing=not fuse_available)
    fake.environment["APPIMAGE_EXTRACT_AND_RUN"] = value
    result, commands = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode != 0
    assert "unset APPIMAGE_EXTRACT_AND_RUN" in result.stderr
    assert "managed service/desktop" in result.stderr and "manual launch-only" in result.stderr
    assert commands == []
    assert not (fake.root / "home/.local").exists()
    assert "service running" not in result.stdout


@pytest.mark.parametrize("value", [None, "0"])
@pytest.mark.parametrize("fuse_available", [False, True])
def test_unset_or_zero_extraction_env_always_requires_normal_fuse(
    tmp_path: Path, value: str | None, fuse_available: bool
) -> None:
    fake, script = app_harness(tmp_path)
    fake.configure(fuse_library_missing=not fuse_available, fuse_runtime_missing=not fuse_available)
    if value is not None:
        fake.environment["APPIMAGE_EXTRACT_AND_RUN"] = value
    result, commands = fake.run("--version", TAG, script=script)
    assert (result.returncode == 0) == fuse_available, result.stderr
    assert ["ldconfig", "-p"] in commands
    if not fuse_available:
        assert "FUSE2 library missing" in result.stderr
        assert mutations(commands) == []
        assert not any(c[0] == "curl" for c in commands)
        assert not (fake.root / "home/.local").exists()
        assert "service running" not in result.stdout


@pytest.mark.parametrize(
    "problem",
    [
        "old-python",
        "config",
        "build",
        "cc",
        "make",
        "dkms",
        "clang",
        "ld.lld",
        "llvm-ar",
        "llvm-nm",
        "llvm-objcopy",
        "llvm-objdump",
        "llvm-readelf",
        "llvm-strip",
    ],
)
@pytest.mark.parametrize("mode", ["--yes", "--preflight"])
def test_optional_build_preflight_blocks_sudo_and_unit_changes(
    tmp_path: Path, problem: str, mode: str
) -> None:
    fake = harness(tmp_path)
    build = fake.root / "modules/fake-kernel/build"
    if problem == "old-python":
        fake.configure(host_python="3.8")
    elif problem == "config":
        (build / ".config").unlink()
    elif problem == "build":
        (build / "Makefile").unlink()
    else:
        (fake.root / "bin" / problem).unlink()
    result, commands = fake.run("--version", TAG, mode)
    assert result.returncode != 0
    assert not any(c[0] in {"sudo", "systemctl", "curl"} for c in commands)
    assert not any(c[0] in {"cc", "make", "dkms", "clang"} for c in commands)
    assert not (fake.root / "home/.local").exists()


def test_inventory_does_not_require_build_preflight(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    (fake.root / "modules/fake-kernel/build/.config").unlink()
    (fake.root / "bin/clang").unlink()
    result, commands = fake.run("--check", "--yes")
    assert result.returncode == 0, result.stderr
    assert not any(c[0] in {"uname", "curl", "sudo", "systemctl"} for c in commands)


def test_missing_kernel_fuse_metadata_fails_without_device_probe(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    (fake.root / "filesystems").write_text("nodev\tfusectl\n")
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode != 0
    assert "kernel FUSE support unavailable" in result.stderr
    assert mutations(commands) == []
    assert not installed_image(fake).exists()


@pytest.mark.parametrize("problem", ["system-python3", "old-python", "headers", "ld.lld"])
@pytest.mark.parametrize("stop_consent", [False, True])
def test_app_optional_preflight_failure_leaves_old_naga_active_and_files_unchanged(
    tmp_path: Path, problem: str, stop_consent: bool
) -> None:
    fake, script = app_harness(tmp_path)
    previous = seed_previous(fake)
    before = json.loads((fake.root / "state.json").read_text())
    files = [installed_image(fake), stamp(fake), *(fake.root / "home" / p for p in USER_FILES)]
    inodes = {path: path.stat().st_ino for path in files}
    fake.stage_openrazer(script.parent / "install_openrazer.sh")
    if problem == "old-python":
        fake.configure(host_python="3.8")
    elif problem == "headers":
        (fake.root / "modules/fake-kernel/build/.config").unlink()
    else:
        (fake.root / "bin" / problem).unlink()
    result, commands = fake.run(
        "--version",
        TAG,
        "--install-openrazer",
        *(["--restart-service"] if stop_consent else []),
        script=script,
    )
    assert result.returncode != 0
    assert "OpenRazer prerequisite preflight failed" in result.stderr
    assert "Naga unchanged" in result.stderr
    assert "Naga remains stopped" not in result.stderr + result.stdout
    assert installed_image(fake).read_bytes() == previous
    assert stamp(fake).read_text() == PREVIOUS_TAG + "\n"
    for relative in USER_FILES:
        assert (fake.root / "home" / relative).read_text() == "previous integration\n"
    after = json.loads((fake.root / "state.json").read_text())
    assert after["service_state"] == before["service_state"] == "active"
    assert after["unit_state"] == before["unit_state"] == "enabled"
    assert {path: path.stat().st_ino for path in files} == inodes
    assert mutations(commands) == []
    assert "Gracefully stop" not in result.stderr and "Naga is running:" not in result.stdout
    assert "app installed;" not in result.stdout and "installation staged:" not in result.stdout
    assert_private_cleanup(fake)


@pytest.mark.parametrize("failure", ["systemd_failure", "bus_failure"])
@pytest.mark.parametrize("mode", ["--yes", "--preflight"])
def test_standalone_optional_session_failure_precedes_package_changes(
    tmp_path: Path, failure: str, mode: str
) -> None:
    fake = harness(tmp_path)
    fake.configure(**{failure: 1})
    result, commands = fake.run("--version", TAG, mode)
    assert result.returncode != 0
    assert "unavailable" in result.stderr
    assert mutations(commands) == []
    assert not any(c[0] == "curl" for c in commands)
    assert not (fake.root / "home/.local").exists()


@pytest.mark.parametrize("env", [None, "1"])
@pytest.mark.parametrize(
    "arguments",
    [(), ("--install",), ("--yes",), ("--add-openrazer-group",), ("--check", "--yes")],
)
def test_standalone_preflight_is_read_only_and_overrides_install_consent(
    tmp_path: Path, env: str | None, arguments: tuple[str, ...]
) -> None:
    fake = harness(tmp_path)
    if env is not None:
        fake.environment["NAGA_CONTROL_INSTALL_OPENRAZER"] = env
    before = (fake.root / "state.json").read_bytes()
    result, commands = fake.run("--preflight", *arguments)
    assert result.returncode == 0, result.stderr
    assert "Read-only install preflight passed" in result.stdout
    assert "builder Python bounds" in result.stdout
    assert not (fake.root / "home/.local").exists()
    assert (fake.root / "state.json").read_bytes() == before
    assert set(map(operation_name, commands)) == {
        "id",
        "uname",
        "system-python3",
        "systemctl-status",
        "busctl",
    }
    assert not list((fake.root / "temporary").iterdir())
    assert "summary confirmation" not in result.stderr


def test_standalone_preflight_env_zero_hard_skips_all_gates(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    fake.environment["NAGA_CONTROL_INSTALL_OPENRAZER"] = "0"
    fake.system_python.unlink()
    result, commands = fake.run("--preflight", "--install", "--yes", "--add-openrazer-group")
    assert result.returncode == 0, result.stderr
    assert "hard skip" in result.stdout
    assert commands == []
    assert not (fake.root / "home/.local").exists()


@pytest.mark.parametrize("value", ["", "yes", "2"])
def test_standalone_preflight_rejects_invalid_env_without_queries(
    tmp_path: Path, value: str
) -> None:
    fake = harness(tmp_path)
    fake.environment["NAGA_CONTROL_INSTALL_OPENRAZER"] = value
    result, commands = fake.run("--preflight", "--install")
    assert result.returncode != 0
    assert "must be 0, 1, or unset" in result.stderr
    assert commands == []
    assert not (fake.root / "home/.local").exists()
