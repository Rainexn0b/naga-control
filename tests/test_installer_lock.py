"""Harmless real flock and FIFO barriers; no sleeps, services or device nodes."""

import json
import os
import selectors
import shutil
import signal
import subprocess
from pathlib import Path

import pytest

from tests.installer_app_fakes import ASSET, app_harness, assert_private_cleanup, mutations
from tests.openrazer_installer_fakes import ROOT, TAG, InstallerHarness


def _start_at_barrier(fake: InstallerHarness, script: Path) -> subprocess.Popen[str]:
    for name in ("barrier-ready", "barrier-release"):
        os.mkfifo(fake.root / name)
    fake.configure(barrier_file=ASSET)
    ready = os.open(fake.root / "barrier-ready", os.O_RDONLY | os.O_NONBLOCK)
    process = subprocess.Popen(
        ["/bin/bash", str(script), "--version", TAG],
        env=fake.environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(ready, selectors.EVENT_READ)
            assert selector.select(timeout=10), "fake download failed to reach its barrier"
            assert os.read(ready, 100) == b"ready\n"
    finally:
        os.close(ready)
    return process


def _release(fake: InstallerHarness) -> None:
    with (fake.root / "barrier-release").open("w") as release:
        release.write("continue\n")


def test_concurrent_second_install_fails_before_shared_mutations(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    first = _start_at_barrier(fake, script)
    lock = fake.root / "home/.local/share/naga-control/install.lock"
    inode = lock.stat().st_ino
    try:
        before = (fake.root / "commands.jsonl").read_text().splitlines()
        result, all_commands = fake.run("--version", TAG, script=script)
        second_commands = all_commands[len(before) :]
        assert result.returncode != 0
        assert "another Naga installer is running" in result.stderr
        assert mutations(second_commands) == []
        assert not any(c[0] == "curl" for c in second_commands)
        before = (fake.root / "commands.jsonl").read_text().splitlines()
        result, all_commands = fake.run("--version", TAG, "--yes")
        assert result.returncode != 0
        assert "another Naga installer is running" in result.stderr
        assert mutations(all_commands[len(before) :]) == []
        assert lock.stat().st_ino == inode
        stage = next((fake.root / "temporary").iterdir())
        assert stage.stat().st_mode & 0o777 == 0o700
    finally:
        _release(fake)
        stdout, stderr = first.communicate(timeout=20)
    assert first.returncode == 0, stdout + stderr
    assert lock.stat().st_ino == inode
    assert_private_cleanup(fake)
    # Successful activation cannot leave the install FD locked in descendants.
    result, _ = fake.run("--version", TAG, "--restart-service", script=script)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("dispatcher", [False, True])
def test_signal_cleans_unique_staging_and_releases_lock(tmp_path: Path, dispatcher: bool) -> None:
    fake, script = app_harness(tmp_path)
    if dispatcher:
        shutil.copyfile(script, fake.remote / "install_user.sh")
        (fake.remote / "uninstall.sh").write_text("exit 0\n")
        script = fake.root / "install.sh"
        shutil.copyfile(ROOT / "install.sh", script)
    first = _start_at_barrier(fake, script)
    # Signal the installer (and downloaded installer when dispatching), never
    # any real runtime process. The blocked fake child finishes at the barrier.
    try:
        stages = list((fake.root / "temporary").iterdir())
        assert len(stages) == (2 if dispatcher else 1)
        assert all(stage.stat().st_mode & 0o777 == 0o700 for stage in stages)
        first.send_signal(signal.SIGTERM)
    finally:
        _release(fake)
        stdout, stderr = first.communicate(timeout=20)
    assert first.returncode != 0, stdout + stderr
    assert_private_cleanup(fake)
    commands = [json.loads(row) for row in (fake.root / "commands.jsonl").read_text().splitlines()]
    assert mutations(commands) == []
