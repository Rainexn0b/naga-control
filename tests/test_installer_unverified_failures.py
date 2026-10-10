"""Stop-time image changes downgrade to quarantine, never trusted rollback."""

import json
import shutil
import sys
from pathlib import Path

from tests.installer_app_fakes import (
    ASSET,
    PREVIOUS_TAG,
    app_harness,
    assert_private_cleanup,
    installed_image,
    quarantines,
    rollbacks,
    seed_altered_previous,
    seed_previous,
    stamp,
)
from tests.openrazer_installer_fakes import TAG

MUTATION_SUFFIX = b"\n# stop-time mutation\n"


def test_stop_time_mutation_never_resumes_unverified(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    previous = seed_previous(fake, active=True)
    fake.configure(mutate_image_on_stop=True, integration_failure=1)
    result, commands = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode != 0
    mutated = previous + MUTATION_SUFFIX
    assert installed_image(fake).read_bytes() == mutated
    assert stamp(fake).read_text() == PREVIOUS_TAG + "\n"
    assert rollbacks(fake) == []
    kept = quarantines(fake)
    assert len(kept) == 1
    assert (kept[0] / "naga-control.AppImage").read_bytes() == mutated
    assert not (kept[0] / "image.sha256").exists()
    marker = (kept[0] / "quarantine").read_text()
    assert "UNVERIFIED" in marker
    assert "changed after stop" in result.stdout + result.stderr
    assert "rollback restored" not in result.stdout + result.stderr
    assert "verified rollback pair retained" not in result.stdout + result.stderr
    assert "not a verified rollback" in result.stdout + result.stderr
    assert not any(c[0] == "systemctl" and c[2] == "start" for c in commands)
    state = json.loads((fake.root / "state.json").read_text())
    assert state["service_state"] == "inactive"
    assert state["unit_state"] == "disabled"
    assert_private_cleanup(fake)


def test_stop_time_mutation_still_allows_verified_upgrade(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    previous = seed_previous(fake, active=True)
    fake.configure(mutate_image_on_stop=True)
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr
    mutated = previous + MUTATION_SUFFIX
    assert installed_image(fake).read_bytes() == (fake.remote / ASSET).read_bytes()
    assert stamp(fake).read_text() == TAG + "\n"
    assert rollbacks(fake) == []
    kept = quarantines(fake)
    assert len(kept) == 1
    assert (kept[0] / "naga-control.AppImage").read_bytes() == mutated
    assert "quarantine" in result.stdout
    assert "verified rollback pair retained" not in result.stdout + result.stderr
    assert "not a verified rollback" in result.stdout + result.stderr
    assert_private_cleanup(fake)


def test_unverified_failure_reports_disable_failure_truthfully(
    tmp_path: Path,
) -> None:
    fake, script = app_harness(tmp_path)
    _, altered = seed_altered_previous(fake, active=True)
    profile = fake.root / "home/.config/naga-control/profiles.toml"
    profile.parent.mkdir(parents=True)
    profile.write_text("user profile untouched\n")
    fake.configure(integration_failure=1, unit_failure="disable")
    result, commands = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "could not disable" in combined
    assert "not disabled" in combined
    assert "stopped and disabled" not in combined
    assert "app installed;" not in result.stdout
    assert "installation staged:" not in result.stdout
    assert "rollback restored" not in combined
    assert "verified rollback pair retained" not in combined
    assert installed_image(fake).read_bytes() == altered
    assert stamp(fake).read_text() == PREVIOUS_TAG + "\n"
    assert profile.read_text() == "user profile untouched\n"
    assert ["systemctl", "--user", "disable", "naga-control.service"] in commands
    assert not any(c[0] == "systemctl" and c[2] == "start" for c in commands)
    assert not any("--now" in c for c in commands)
    state = json.loads((fake.root / "state.json").read_text())
    assert state["service_state"] == "inactive"
    assert state["unit_state"] == "enabled"
    kept = quarantines(fake)
    assert len(kept) == 1
    assert (kept[0] / "naga-control.AppImage").read_bytes() == altered
    assert (kept[0] / "installed-tag").read_text() == PREVIOUS_TAG + "\n"
    assert rollbacks(fake) == []
    assert_private_cleanup(fake)


def test_unverified_atomic_replace_failure_keeps_old_and_quarantine(
    tmp_path: Path,
) -> None:
    fake, script = app_harness(tmp_path)
    _, altered = seed_altered_previous(fake, active=True)
    profile = fake.root / "home/.config/naga-control/profiles.toml"
    profile.parent.mkdir(parents=True)
    profile.write_text("user profile untouched\n")
    real_mv = shutil.which("mv")
    assert real_mv is not None
    target = str(installed_image(fake))
    wrapper = fake.root / "bin" / "mv"
    wrapper.unlink()
    wrapper.write_text(
        f"#!{sys.executable}\n"
        "import os\n"
        "import sys\n"
        f"real_mv = {real_mv!r}\n"
        f"target = {target!r}\n"
        "args = sys.argv[1:]\n"
        "if args and args[-1] == target:\n"
        '    sys.stderr.write("fake mv failure for AppImage\\n")\n'
        "    sys.exit(1)\n"
        "os.execv(real_mv, [real_mv, *args])\n"
    )
    wrapper.chmod(0o755)
    result, commands = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "atomic AppImage replacement failed" in combined
    assert "unverified" in combined
    assert "manual recovery" in combined
    assert "app installed;" not in result.stdout
    assert "installation staged:" not in result.stdout
    assert "rollback restored" not in combined
    assert "verified rollback pair retained" not in combined
    assert installed_image(fake).read_bytes() == altered
    assert stamp(fake).read_text() == PREVIOUS_TAG + "\n"
    assert profile.read_text() == "user profile untouched\n"
    assert not any(c[0] == "systemctl" and c[2] == "start" for c in commands)
    assert not any("--now" in c for c in commands)
    state = json.loads((fake.root / "state.json").read_text())
    assert state["service_state"] == "inactive"
    assert state["unit_state"] == "disabled"
    kept = quarantines(fake)
    assert len(kept) == 1
    assert (kept[0] / "naga-control.AppImage").read_bytes() == altered
    assert (kept[0] / "installed-tag").read_text() == PREVIOUS_TAG + "\n"
    assert rollbacks(fake) == []
    assert_private_cleanup(fake)
