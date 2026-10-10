"""Hermetic installer fake identity: default id matches fixture owner."""

import json
import os
import subprocess
import sys
from pathlib import Path

from tests.installer_app_fakes import app_harness
from tests.installer_command_fakes import FAKE
from tests.openrazer_installer_fakes import TAG, harness


def _run_real_id(root: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(root / "bin" / "id"), "-u"],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def _run_simulated_id(
    root: Path, env: dict[str, str], simulated_uid: int
) -> subprocess.CompletedProcess[str]:
    """Run the installer FAKE with only os.getuid patched in the child.

    The header is injected before the FAKE prolog so the default branch
    observes the simulated desktop UID. No host UID, ownership, or
    namespace changes occur; the child only reads fixture state.json and
    appends to fixture commands.jsonl.
    """
    sim_dir = root / f"sim-{simulated_uid}"
    sim_dir.mkdir(exist_ok=True)
    target = sim_dir / "id"
    header = f"import os\nos.getuid = lambda: {simulated_uid}  # hermetic simulated UID\n"
    target.write_text(f"#!{sys.executable}\n{header}{FAKE}")
    target.chmod(0o755)
    return subprocess.run(
        [str(target), "-u"],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def test_default_id_matches_fixture_owner_and_stat(tmp_path: Path) -> None:
    fake, _ = app_harness(tmp_path)
    state = json.loads((fake.root / "state.json").read_text())
    assert "uid" not in state
    result = _run_real_id(fake.root, fake.environment)
    assert result.returncode == 0, result.stderr
    owner = (fake.root / "home").stat().st_uid
    assert result.stdout.strip() == str(os.getuid())
    assert result.stdout.strip() == str(owner)
    probed = subprocess.run(
        [str(fake.root / "bin" / "stat"), "-c", "%u", str(fake.root / "home")],
        env=fake.environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert probed.returncode == 0, probed.stderr
    assert probed.stdout.strip() == result.stdout.strip()


def test_simulated_desktop_uid_1001(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    result = _run_simulated_id(fake.root, fake.environment, 1001)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1001"


def test_simulated_desktop_uid_2000(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    result = _run_simulated_id(fake.root, fake.environment, 2000)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "2000"


def test_explicit_root_override_wins_over_simulated_default(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    fake.configure(uid="0")
    simulated = _run_simulated_id(fake.root, fake.environment, 1001)
    assert simulated.returncode == 0, simulated.stderr
    assert simulated.stdout.strip() == "0"
    real = _run_real_id(fake.root, fake.environment)
    assert real.returncode == 0, real.stderr
    assert real.stdout.strip() == "0"


def test_explicit_foreign_override_stays_distinct(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    owner = (fake.root / "home").stat().st_uid
    foreign = str(owner + 1)
    assert foreign != str(owner)
    fake.configure(uid=foreign)
    result = _run_real_id(fake.root, fake.environment)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == foreign


def test_explicit_root_still_rejected_without_mutations(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    fake.configure(uid="0")
    result, _ = fake.run("--version", TAG, script=script)
    assert result.returncode != 0
    assert "run as your desktop user, not root" in result.stderr
    assert not (fake.root / "home/.local").exists()
