"""Session bootstrap: same-ref helper fetch and old-ref compatibility."""

import shutil
from pathlib import Path

from tests.installer_app_fakes import app_harness, assert_private_cleanup
from tests.openrazer_installer_fakes import ROOT, TAG, harness, stage_app_installer

MARKER = ".local/share/naga-control/service-manager"


def test_bootstrap_fetches_same_ref_helper(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    script = stage_app_installer(fake)
    shutil.copyfile(script, fake.remote / "install_user.sh")
    (fake.remote / "uninstall.sh").write_text("exit 0\n")
    (fake.remote / "session_service.sh").write_text(
        (ROOT / "scripts/session_service.sh").read_text()
    )
    dispatcher = fake.root / "install.sh"
    shutil.copyfile(ROOT / "install.sh", dispatcher)
    fake.configure(bus_available=True, has_owner=False)
    result, commands = fake.run(
        "--ref",
        "new-ref",
        "--version",
        TAG,
        "--service-manager",
        "session",
        script=dispatcher,
    )
    assert result.returncode == 0, result.stderr
    urls = [i for c in commands if c[0] == "curl" for i in c if "https:" in i]
    assert (
        "https://raw.githubusercontent.com/Rainexn0b/naga-control/new-ref/scripts/session_service.sh"
        in urls
    )
    assert (fake.root / "home" / MARKER).read_text() == "session\n"
    assert_private_cleanup(fake)


def test_old_ref_without_marker_needs_no_helper(tmp_path: Path) -> None:
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
    assert not any("session_service.sh" in i for c in commands for i in c)
    assert not any(c[0] in {"sudo", "systemctl"} for c in commands)


def test_local_checkout_uses_sibling_without_helper_fetch(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    fake.configure(bus_available=True, has_owner=False)
    result, commands = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode == 0, result.stderr
    assert not any("session_service.sh" in i for c in commands for i in c)
    assert (fake.root / "home" / MARKER).read_text() == "session\n"
    assert_private_cleanup(fake)


def test_missing_sibling_helper_fails_clearly(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    (script.parent / "session_service.sh").unlink()
    fake.configure(bus_available=True, has_owner=False)
    result, _ = fake.run("--version", TAG, "--service-manager", "session", script=script)
    assert result.returncode != 0
    assert "helper" in result.stderr.lower()
    assert_private_cleanup(fake)


def test_dispatcher_forwards_service_manager_flag(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    script = stage_app_installer(fake)
    shutil.copyfile(script, fake.remote / "install_user.sh")
    (fake.remote / "uninstall.sh").write_text("exit 0\n")
    (fake.remote / "session_service.sh").write_text(
        (ROOT / "scripts/session_service.sh").read_text()
    )
    dispatcher = fake.root / "install.sh"
    shutil.copyfile(ROOT / "install.sh", dispatcher)
    fake.configure(bus_available=True, has_owner=False)
    result, _ = fake.run(
        "--ref",
        "new-ref",
        "--version",
        TAG,
        "--service-manager",
        "session",
        script=dispatcher,
    )
    assert result.returncode == 0, result.stderr
    assert "service manager: session" in result.stdout
    assert_private_cleanup(fake)
