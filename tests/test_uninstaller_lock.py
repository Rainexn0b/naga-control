"""Stable shared install lock, owner/path preflight, and fake-child FD hygiene."""

import fcntl
import os
import selectors
import subprocess
from pathlib import Path

import pytest

from tests.installer_app_fakes import app_harness, seed_previous
from tests.openrazer_installer_fakes import TAG
from tests.uninstaller_fakes import (
    STATE,
    assert_no_cleanup,
    assert_retained,
    harness,
    stage_uninstaller,
)


def test_lock_inode_and_contents_retained_across_success_and_second_uninstall(
    tmp_path: Path,
) -> None:
    fake = harness(tmp_path)
    fake.seed()
    fake.lock.write_text("stable shared inode\n")
    fake.lock.chmod(0o600)
    inode = fake.lock.stat().st_ino
    state_mode = fake.lock.parent.stat().st_mode
    for _ in range(2):
        result, _ = fake.run("--yes")
        assert result.returncode == 0, result.stderr
        assert fake.lock.stat().st_ino == inode
        assert fake.lock.read_text() == "stable shared inode\n"
        assert fake.lock.parent.stat().st_mode == state_mode
    with fake.lock.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_missing_state_is_created_privately_and_not_removed(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    fake.configure(ActiveState="inactive", UnitFileState="", LoadState="not-found")
    result, _ = fake.run("--yes")
    assert result.returncode == 0, result.stderr
    for relative in (".local", ".local/share", STATE):
        assert (fake.home / relative).stat().st_mode & 0o777 == 0o700
    assert fake.lock.stat().st_mode & 0o777 == 0o600
    assert fake.lock.stat().st_uid == os.getuid()


@pytest.mark.parametrize(
    "unsafe",
    [
        "lock-directory",
        "lock-fifo",
        "lock-symlink",
        "state-symlink",
        "state-writable",
        "home-writable",
        "asset-ancestor-writable",
    ],
)
def test_unsafe_lock_or_directory_permissions_refused_before_service_or_cleanup(
    tmp_path: Path, unsafe: str
) -> None:
    fake = harness(tmp_path)
    contents = fake.seed()
    if unsafe == "lock-directory":
        fake.lock.mkdir()
    elif unsafe == "lock-fifo":
        os.mkfifo(fake.lock)
    elif unsafe == "lock-symlink":
        foreign = fake.root / "foreign-lock"
        foreign.write_text("keep foreign lock\n")
        fake.lock.symlink_to(foreign)
    elif unsafe == "state-symlink":
        foreign = fake.root / "foreign-state"
        fake.lock.parent.rename(foreign)
        fake.lock.parent.symlink_to(foreign, target_is_directory=True)
    else:
        directory = {
            "state-writable": fake.lock.parent,
            "home-writable": fake.home,
            "asset-ancestor-writable": fake.home / ".config/systemd/user",
        }[unsafe]
        directory.chmod(0o777)
    result, commands = fake.run("--yes")
    assert result.returncode != 0
    assert_retained(fake, contents)
    assert_no_cleanup(commands)
    assert not any(command[0] == "systemctl" for command in commands)
    if unsafe == "lock-symlink":
        assert (fake.root / "foreign-lock").read_text() == "keep foreign lock\n"


def test_held_shared_lock_prevents_every_uninstall_mutation(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    contents = fake.seed()
    backup = fake.backup()
    fake.lock.write_text("held installer lock\n")
    inode = fake.lock.stat().st_ino
    with fake.lock.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result, commands = fake.run("--yes", "--purge-config")
        assert result.returncode != 0
        assert "another Naga installer is running" in result.stderr
        assert_retained(fake, contents)
        assert (backup / "naga-control.AppImage").is_file()
        assert_no_cleanup(commands)
        assert not any(command[0] == "systemctl" for command in commands)
        assert fake.lock.stat().st_ino == inode
        assert fake.lock.read_text() == "held installer lock\n"


def test_real_fake_installer_overlap_blocks_uninstall_without_replacing_lock(
    tmp_path: Path,
) -> None:
    fake, installer = app_harness(tmp_path)
    previous = seed_previous(fake)
    uninstall = stage_uninstaller(fake.root)
    for name in ("barrier-ready", "barrier-release"):
        os.mkfifo(fake.root / name)
    fake.configure(barrier_file="Naga-Control-x86_64.AppImage")
    ready = os.open(fake.root / "barrier-ready", os.O_RDONLY | os.O_NONBLOCK)
    first = subprocess.Popen(
        ["/bin/bash", str(installer), "--version", TAG, "--restart-service"],
        env=fake.environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(ready, selectors.EVENT_READ)
            assert selector.select(timeout=10), "fake installer did not reach download barrier"
            assert os.read(ready, 100) == b"ready\n"
        lock = fake.root / "home" / STATE / "install.lock"
        inode = lock.stat().st_ino
        before = (fake.root / "commands.jsonl").read_text().splitlines()
        result, commands = fake.run("--yes", "--purge-config", script=uninstall)
        assert result.returncode != 0
        assert "another Naga installer is running" in result.stderr
        assert (fake.root / "home/.local/bin/naga-control.AppImage").read_bytes() == previous
        assert_no_cleanup(commands[len(before) :])
        assert not any(command[0] == "systemctl" for command in commands[len(before) :])
        assert lock.stat().st_ino == inode
    finally:
        os.close(ready)
        with (fake.root / "barrier-release").open("w") as release:
            release.write("continue\n")
        stdout, stderr = first.communicate(timeout=20)
    assert first.returncode == 0, stdout + stderr
    assert lock.stat().st_ino == inode


def test_service_and_privilege_children_close_fd9_while_parent_keeps_lock(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    fake.seed()
    fake.rule.parent.mkdir()
    fake.rule.write_text("rule\n")
    result, commands = fake.run("--yes")
    assert result.returncode == 0, result.stderr
    # Every fake service/sudo command asserts FD 9 is closed and a separately
    # opened descriptor still cannot take the lock while the parent is alive.
    assert ["systemctl", "--user", "stop", "naga-control.service"] in commands
    assert ["systemctl", "--user", "daemon-reload"] in commands
    assert ["sudo", "udevadm", "control", "--reload"] in commands
