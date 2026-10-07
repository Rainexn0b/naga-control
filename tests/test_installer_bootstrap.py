"""Dispatcher/app opt-in contracts, including older bootstrap refs and failure."""

import os
import pty
import shutil
from pathlib import Path

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
from tests.openrazer_installer_fakes import ROOT, TAG, harness, stage_app_installer


@pytest.mark.parametrize("opt_in", ["default", "flag", "env1", "env0", "env0-flag"])
def test_app_opt_in_and_hard_skip(tmp_path: Path, opt_in: str) -> None:
    fake = harness(tmp_path)
    script = stage_app_installer(fake, helper=HELPER_OK)
    args = ["--version", TAG]
    if "flag" in opt_in:
        args.append("--install-openrazer")
    if opt_in.startswith("env"):
        fake.environment["NAGA_CONTROL_INSTALL_OPENRAZER"] = opt_in[3]
    result, commands = fake.run(*args, script=script)
    assert result.returncode == 0, result.stderr
    opted_in = opt_in in {"flag", "env1"}
    assert ("fake prerequisite called" in result.stdout) == opted_in
    assert ("fake prerequisite preflight" in result.stdout) == opted_in
    if opted_in:
        assert f"--version {TAG} --install" in result.stdout
        assert ["systemctl", "--user", "enable", "naga-control.service"] in commands
        assert not any("--now" in command for command in commands)
        assert "reboot/re-login" in result.stdout
    else:
        assert ["systemctl", "--user", "enable", "--now", "naga-control.service"] in commands
    assert not any("install_openrazer.sh" in item for command in commands for item in command)


@pytest.mark.parametrize("value", ["", "yes", "2"])
def test_app_invalid_env_fails_before_network(tmp_path: Path, value: str) -> None:
    fake = harness(tmp_path)
    script = stage_app_installer(fake)
    fake.environment["NAGA_CONTROL_INSTALL_OPENRAZER"] = value
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode != 0
    assert "must be 0, 1, or unset" in result.stderr
    assert not any(command[0] in {"curl", "sudo", "systemctl"} for command in commands)


@pytest.mark.parametrize("helper", [None, "exit 42\n"])
def test_opt_in_helper_failure_precedes_app_install(tmp_path: Path, helper: str | None) -> None:
    fake = harness(tmp_path)
    script = stage_app_installer(fake, helper=helper)
    result, commands = fake.run("--version", TAG, "--install-openrazer", script=script)
    assert result.returncode != 0
    assert "done:" not in result.stdout
    assert mutations(commands) == []
    # Stronger ordering: checksum/app downloads precede dependency mutation,
    # but failed dependencies still prevent all app execution/activation.
    assert any(ASSET in item for command in commands for item in command)


def test_actual_helper_validation_failure_propagates_to_app(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    script = stage_app_installer(fake)
    fake.stage_openrazer(script.parent / "install_openrazer.sh")
    seed_previous(fake)
    # The real helper must not mistake explicit app opt-in for noninteractive --yes.
    result, commands = fake.run(
        "--version", TAG, "--install-openrazer", "--restart-service", script=script
    )
    assert result.returncode != 0
    assert "summary confirmation requires a terminal" in result.stderr
    assert "OpenRazer prerequisite step failed" in result.stderr
    assert "done:" not in result.stdout
    assert mutations(commands) == [["systemctl", "--user", "stop", "naga-control.service"]]


def test_actual_helper_inherits_app_lock_and_precedes_execution_not_verification(
    tmp_path: Path,
) -> None:
    fake = harness(tmp_path)
    script = stage_app_installer(fake)
    fake.stage_openrazer(script.parent / "install_openrazer.sh")
    seed_previous(fake)
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n")
        result, commands = fake.run(
            "--version",
            TAG,
            "--install-openrazer",
            "--restart-service",
            script=script,
            input_fd=slave,
        )
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode == 0, result.stderr
    package = next(i for i, c in enumerate(commands) if c[:2] == ["sudo", "pacman"])
    app_download = next(
        i for i, c in enumerate(commands) if c[0] == "curl" and c[-1].endswith("/" + ASSET)
    )
    execution = next(i for i, c in enumerate(commands) if c[0] == ASSET)
    stop = commands.index(["systemctl", "--user", "stop", "naga-control.service"])
    checks = [
        i
        for i, c in enumerate(commands)
        if c[0] == "system-python3" and any("sys.exit(0 if sys.version_info" in arg for arg in c)
    ]
    assert len(checks) == 2
    assert app_download < checks[0] < stop < checks[1] < package < execution
    assert not any("--now" in c for c in commands)


def test_documented_one_liner_pins_all_refs_preserves_stdin_and_cleans(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    (fake.remote / "install.sh").write_text(
        'printf "args: %s\\n" "$*"; read -r reply; printf "stdin: %s\\n" "$reply"\n'
    )
    command = next(
        line
        for line in (ROOT / "README.md").read_text().splitlines()
        if line.startswith("(umask 077; d=")
    )
    assert "/v0.4.0/install.sh" in command
    assert "--ref v0.4.0 --version v0.4.0" in command
    assert "curl|bash" not in command and "<(" not in command
    script = fake.root / "one-liner.sh"
    script.write_text(command + "\n")
    master, slave = pty.openpty()
    try:
        os.write(master, b"preserved\n")
        result, _ = fake.run(script=script, input_fd=slave)
    finally:
        os.close(master)
        os.close(slave)
    assert result.returncode == 0, result.stderr
    assert "args: --ref v0.4.0 --version v0.4.0" in result.stdout
    assert "stdin: preserved" in result.stdout
    assert not list((fake.root / "temporary").iterdir())


@pytest.mark.parametrize("failure", ["daemon-reload", "enable"])
def test_app_unit_failure_after_opt_in_is_visible(tmp_path: Path, failure: str) -> None:
    fake = harness(tmp_path)
    script = stage_app_installer(fake, helper=HELPER_OK)
    fake.configure(unit_failure=failure)
    result, _ = fake.run("--version", TAG, "--install-openrazer", script=script)
    assert result.returncode != 0
    assert "Naga user-unit" in result.stderr
    assert "failed" in result.stderr
    assert "installation staged:" not in result.stdout
    assert "done:" not in result.stdout


def test_missing_opted_in_helper_fetched_only_from_selected_release(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    script = stage_app_installer(fake)
    (fake.remote / "install_openrazer.sh").write_text(HELPER_OK)
    result, commands = fake.run("--version", TAG, "--install-openrazer", script=script)
    assert result.returncode == 0, result.stderr
    urls = [
        item for command in commands if command[0] == "curl" for item in command if "https:" in item
    ]
    assert (
        urls[-1]
        == f"https://raw.githubusercontent.com/Rainexn0b/naga-control/{TAG}/scripts/install_openrazer.sh"
    )
    assert "fake prerequisite called" in result.stdout
    assert not any("--now" in command for command in commands)


@pytest.mark.parametrize("downloaded", [False, True])
def test_legacy_helper_missing_preflight_support_fails_before_naga_stop(
    tmp_path: Path, downloaded: bool
) -> None:
    legacy = 'echo "error: unknown argument: --preflight" >&2; exit 1\n'
    fake, script = app_harness(tmp_path, helper=None if downloaded else legacy)
    previous = seed_previous(fake)
    if downloaded:
        (fake.remote / "install_openrazer.sh").write_text(legacy)
    result, commands = fake.run(
        "--version", TAG, "--install-openrazer", "--restart-service", script=script
    )
    assert result.returncode != 0
    assert "unknown argument: --preflight" in result.stderr
    assert "requires a helper supporting --preflight (no legacy fallback)" in result.stderr
    assert mutations(commands) == []
    assert installed_image(fake).read_bytes() == previous
    assert_private_cleanup(fake)


def test_optional_helper_phase_order_is_verified_preflight_stop_install_then_integration(
    tmp_path: Path,
) -> None:
    fake, script = app_harness(tmp_path, helper=HELPER_OK)
    seed_previous(fake)
    result, commands = fake.run(
        "--version", TAG, "--install-openrazer", "--restart-service", script=script
    )
    assert result.returncode == 0, result.stderr
    preflight = commands.index(["installer-helper", "--version", TAG, "--preflight"])
    stop = commands.index(["systemctl", "--user", "stop", "naga-control.service"])
    install = commands.index(["installer-helper", "--version", TAG, "--install"])
    execution = next(i for i, c in enumerate(commands) if c[0] == ASSET)
    assert all(i < preflight for i, c in enumerate(commands) if c[0] == "curl")
    assert preflight < stop < install < execution
    assert [c for c in commands if c[0] == "installer-helper"] == [
        ["installer-helper", "--version", TAG, "--preflight"],
        ["installer-helper", "--version", TAG, "--install"],
    ]


@pytest.mark.parametrize("opt_in", [False, True])
def test_dispatcher_forwards_flag_without_unconditional_helper_fetch(
    tmp_path: Path, opt_in: bool
) -> None:
    fake = harness(tmp_path)
    script = stage_app_installer(fake)
    shutil.copyfile(script, fake.remote / "install_user.sh")
    (fake.remote / "uninstall.sh").write_text("exit 0\n")
    (fake.remote / "install_openrazer.sh").write_text(HELPER_OK)
    dispatcher = fake.root / "install.sh"
    shutil.copyfile(ROOT / "install.sh", dispatcher)
    args = ["--ref", "old-ref", "--version", TAG]
    if opt_in:
        args.append("--install-openrazer")
    result, commands = fake.run(*args, script=dispatcher)
    assert result.returncode == 0, result.stderr
    urls = [
        item for command in commands if command[0] == "curl" for item in command if "https:" in item
    ]
    assert urls[:2] == [
        "https://raw.githubusercontent.com/Rainexn0b/naga-control/old-ref/scripts/install_user.sh",
        "https://raw.githubusercontent.com/Rainexn0b/naga-control/old-ref/scripts/uninstall.sh",
    ]
    helpers = [url for url in urls if url.endswith("install_openrazer.sh")]
    assert helpers == (
        [
            f"https://raw.githubusercontent.com/Rainexn0b/naga-control/{TAG}/scripts/install_openrazer.sh"
        ]
        if opt_in
        else []
    )


def test_older_bootstrap_works_without_optional_helper(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    (fake.remote / "install_user.sh").write_text(
        "#!/usr/bin/env bash\nprintf 'older installer: %s\\n' \"$*\"\n"
    )
    (fake.remote / "uninstall.sh").write_text("exit 0\n")
    dispatcher = fake.root / "install.sh"
    shutil.copyfile(ROOT / "install.sh", dispatcher)
    result, commands = fake.run("--ref", "v0.3.0", "--version", "v0.3.0", script=dispatcher)
    assert result.returncode == 0, result.stderr
    assert "older installer: --version v0.3.0" in result.stdout
    assert not any("install_openrazer.sh" in item for command in commands for item in command)
    assert not any(command[0] in {"sudo", "systemctl"} for command in commands)


@pytest.mark.parametrize("value", ["", "invalid"])
def test_dispatcher_rejects_invalid_env_before_bootstrap(tmp_path: Path, value: str) -> None:
    fake = harness(tmp_path)
    dispatcher = fake.root / "install.sh"
    shutil.copyfile(ROOT / "install.sh", dispatcher)
    fake.environment["NAGA_CONTROL_INSTALL_OPENRAZER"] = value
    result, commands = fake.run("--ref", "v0.3.0", script=dispatcher)
    assert result.returncode != 0
    assert "must be 0, 1, or unset" in result.stderr
    assert commands == []


def test_app_accepts_safe_build_metadata_release_tag(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    script = stage_app_installer(fake, helper=HELPER_OK)
    tag = TAG + "+fixture.1"
    result, commands = fake.run("--version", tag, "--install-openrazer", script=script)
    assert result.returncode == 0, result.stderr
    assert f"--version {tag} --install" in result.stdout
    assert any(f"/releases/download/{tag}/" in item for command in commands for item in command)


def test_helper_accepts_safe_build_metadata_release_tag(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    tag = TAG + "+fixture.1"
    result, commands = fake.run("--version", tag, "--yes")
    assert result.returncode == 0, result.stderr
    assert any(
        f"/{tag}/buildpython/openrazer_packages/pin.conf" in item
        for command in commands
        for item in command
    )


@pytest.mark.parametrize("tag", ["../tag", "refs/tags/v0.4.0", "v0.4.0?query", "v0.4.0#fragment"])
@pytest.mark.parametrize("app", [False, True])
def test_tag_paths_and_query_fragments_remain_rejected(tmp_path: Path, tag: str, app: bool) -> None:
    fake = harness(tmp_path)
    script = stage_app_installer(fake) if app else None
    result, commands = fake.run("--version", tag, *([] if app else ["--yes"]), script=script)
    assert result.returncode != 0
    assert "invalid release tag" in result.stderr
    assert not any(command[0] in {"curl", "sudo", "systemctl"} for command in commands)
