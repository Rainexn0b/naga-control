"""Strict AppImage bytes/sidecar checks happen before execution or mutation."""

import hashlib
from pathlib import Path

import pytest

from tests.installer_app_fakes import (
    ASSET,
    HELPER_OK,
    app_harness,
    assert_private_cleanup,
    installed_image,
    mutations,
    quarantines,
    rollbacks,
    stamp,
)
from tests.openrazer_installer_fakes import TAG


@pytest.mark.parametrize(
    "problem",
    [
        "missing",
        "uppercase",
        "bad-digest",
        "traversal",
        "absolute",
        "wrong-name",
        "duplicate",
        "extra",
        "blank",
        "crlf",
        "nul",
        "no-newline",
        "binary",
        "one-space",
        "mismatch",
        "empty",
    ],
)
def test_hash_failure_before_any_execute_stop_or_privilege(tmp_path: Path, problem: str) -> None:
    fake, script = app_harness(tmp_path, helper=HELPER_OK)
    fake.configure(service_state="active")
    manifest = fake.remote / (ASSET + ".sha256")
    row = manifest.read_text()
    if problem == "missing":
        manifest.unlink()
    elif problem in {"mismatch", "empty"}:
        (fake.remote / ASSET).write_bytes(b"tampered" if problem == "mismatch" else b"")
    else:
        alternatives = {
            "uppercase": row[:64].upper() + row[64:],
            "bad-digest": "z" + row[1:],
            "traversal": row.replace("  ", "  ../"),
            "absolute": row.replace("  ", "  /tmp/"),
            "wrong-name": row.replace(ASSET, "another.AppImage"),
            "duplicate": row + row,
            "extra": row + "extra\n",
            "blank": row + "\n",
            "crlf": row.replace("\n", "\r\n"),
            "nul": row.rstrip("\n") + "\0\n",
            "no-newline": row.rstrip("\n"),
            "binary": row.replace("  ", " *"),
            "one-space": row.replace("  ", " "),
        }
        manifest.write_bytes(alternatives[problem].encode())
    result, commands = fake.run(
        "--version", TAG, "--install-openrazer", "--restart-service", script=script
    )
    assert result.returncode != 0
    assert "fake prerequisite" not in result.stdout
    assert not any(c[0] == "installer-helper" for c in commands)
    assert mutations(commands) == []
    assert not installed_image(fake).exists()
    assert not stamp(fake).exists()
    assert "app installed;" not in result.stdout
    if problem == "missing":
        assert "older releases without the sidecar" in result.stderr
    assert_private_cleanup(fake)


@pytest.mark.parametrize("corrupt", [False, True])
def test_same_tag_local_image_is_hashed_not_trusted_by_stamp(tmp_path: Path, corrupt: bool) -> None:
    fake, script = app_harness(tmp_path)
    image = installed_image(fake)
    image.parent.mkdir(parents=True)
    image.write_bytes(b"corrupt" if corrupt else (fake.remote / ASSET).read_bytes())
    image.chmod(0o755)
    stamp(fake).parent.mkdir(parents=True)
    stamp(fake).write_text(TAG + "\n")
    inode = image.stat().st_ino
    result, commands = fake.run("--version", TAG, script=script)
    assert any(c[0] == "curl" and c[-1].endswith(f"/{TAG}/{ASSET}.sha256") for c in commands)
    if corrupt:
        # Same-tag corruption repairs from a verified download: the old bytes
        # are quarantined privately before replacement, then pruned after the
        # committed success. No unverified bytes are executed or retained.
        assert result.returncode == 0, result.stderr
        assert any(c[0] == "curl" and c[-1].endswith("/" + ASSET) for c in commands)
        assert image.stat().st_ino != inode
        assert image.read_bytes() == (fake.remote / ASSET).read_bytes()
        assert "warning" in result.stdout and "quarantine" in result.stdout
        assert "held until successful commit then removed" in result.stdout
        assert "removed unverified quarantine" in result.stdout
        assert "verified local bytes before reuse" not in result.stdout
        assert quarantines(fake) == []
        assert rollbacks(fake) == []
    else:
        assert result.returncode == 0, result.stderr
        assert not any(c[0] == "curl" and c[-1].endswith("/" + ASSET) for c in commands)
        assert "verified local bytes before reuse" in result.stdout
        assert quarantines(fake) == []
    assert_private_cleanup(fake)


def test_same_tag_empty_repairs_from_verified_download(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    image = installed_image(fake)
    image.parent.mkdir(parents=True)
    image.write_bytes(b"")
    image.chmod(0o755)
    stamp(fake).parent.mkdir(parents=True)
    stamp(fake).write_text(TAG + "\n")
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert any(c[0] == "curl" and c[-1].endswith("/" + ASSET) for c in commands)
    assert image.read_bytes() == (fake.remote / ASSET).read_bytes()
    assert "removed unverified quarantine" in result.stdout
    assert quarantines(fake) == []
    assert rollbacks(fake) == []
    assert_private_cleanup(fake)


def test_force_never_skips_new_verification(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    image = installed_image(fake)
    image.parent.mkdir(parents=True)
    image.write_bytes(b"corrupt")
    image.chmod(0o755)
    stamp(fake).parent.mkdir(parents=True)
    stamp(fake).write_text(TAG + "\n")
    (fake.remote / ASSET).write_bytes(b"tampered-new")
    fake.environment["NAGA_CONTROL_FORCE_DOWNLOAD"] = "1"
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr
    assert mutations(commands) == []
    assert image.read_bytes() == b"corrupt"
    assert quarantines(fake) == []
    assert_private_cleanup(fake)


def test_valid_release_hash_matches_downloaded_bytes_and_exact_tag(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    expected = hashlib.sha256((fake.remote / ASSET).read_bytes()).hexdigest()
    assert hashlib.sha256(installed_image(fake).read_bytes()).hexdigest() == expected
    assert [c[-1] for c in commands if c[0] == "curl" and "/releases/download/" in c[-1]] == [
        f"https://github.com/Rainexn0b/naga-control/releases/download/{TAG}/{ASSET}.sha256",
        f"https://github.com/Rainexn0b/naga-control/releases/download/{TAG}/{ASSET}",
    ]
    assert_private_cleanup(fake)
