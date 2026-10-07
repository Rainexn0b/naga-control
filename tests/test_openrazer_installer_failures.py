"""Validation rejects incomplete/untrusted cohorts before privileged operations."""

from pathlib import Path

import pytest

from tests.openrazer_installer_fakes import NAMES, PIN, ROLES, TAG, harness, operation_name


@pytest.mark.parametrize(
    "problem",
    [
        "missing",
        "extra",
        "duplicate",
        "mixed-version",
        "bad-digest",
        "uppercase-digest",
        "path",
        "traversal",
        "unsafe",
        "blank",
        "binary-mode-row",
    ],
)
def test_entire_manifest_validated_before_package_download_or_sudo(
    tmp_path: Path, problem: str
) -> None:
    fake = harness(tmp_path)
    manifest = fake.remote / "openrazer-arch-packages.sha256"
    rows = manifest.read_text().splitlines()
    if problem == "missing":
        rows.pop()
    elif problem == "extra":
        rows.append(rows[0])
    elif problem == "duplicate":
        rows[1] = rows[0]
    elif problem == "mixed-version":
        rows[1] = rows[1].replace("fix2", "fix1")
    elif problem == "bad-digest":
        rows[0] = "z" + rows[0][1:]
    elif problem == "uppercase-digest":
        rows[0] = rows[0][:64].upper() + rows[0][64:]
    elif problem in {"path", "traversal"}:
        rows[0] = rows[0].replace("  ", "  /tmp/" if problem == "path" else "  ../")
    elif problem == "unsafe":
        rows[0] += ";echo"
    elif problem == "blank":
        rows[1] = ""
    else:
        rows[0] = rows[0].replace("  ", " *")
    manifest.write_text("\n".join(rows) + "\n")
    result, commands = fake.run("--yes", "--version", TAG)
    assert result.returncode != 0
    assert "invalid release manifest/source pin" in result.stderr
    assert not any(
        operation_name(command) in {"sudo", "systemctl", "bsdtar"} for command in commands
    )
    assert not any(
        item.endswith(".pkg.tar.zst")
        for command in commands
        if command[0] == "curl"
        for item in command
    )


@pytest.mark.parametrize("filename", ["pin.conf", "openrazer-arch-packages.sha256", *NAMES])
def test_download_failure_is_not_success(tmp_path: Path, filename: str) -> None:
    fake = harness(tmp_path)
    fake.configure(download_fail=[filename])
    result, commands = fake.run("--yes", "--version", TAG)
    assert result.returncode != 0
    assert not any(operation_name(command) in {"sudo", "systemctl"} for command in commands)
    assert "Packages installed" not in result.stdout


def test_all_three_checksums_required(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    (fake.remote / NAMES[2]).write_text("tampered client\n")
    result, commands = fake.run("--yes", "--version", TAG)
    assert result.returncode != 0
    assert "package checksum verification failed" in result.stderr
    assert NAMES[2] + ": FAILED" in result.stdout
    assert not any(
        operation_name(command) in {"sudo", "systemctl", "bsdtar"} for command in commands
    )


@pytest.mark.parametrize(
    "problem", ["wrong-sha", "wrong-repo", "execution", "duplicate", "missing", "missing-branch"]
)
def test_pin_is_validated_data_never_executed(tmp_path: Path, problem: str) -> None:
    fake = harness(tmp_path)
    pin = fake.remote / "pin.conf"
    text = pin.read_text()
    if problem == "wrong-sha":
        text = text.replace(PIN, "a" * 40)
    elif problem == "wrong-repo":
        text = text.replace("Rainexn0b/openrazer", "other/openrazer")
    elif problem == "execution":
        text += 'sudo echo "should never execute"\n'
    elif problem == "duplicate":
        text += 'OPENRAZER_PKGREL="1"\n'
    elif problem == "missing-branch":
        text = text.replace('OPENRAZER_BRANCH="test-pr-2904-edualb"\n', "")
    else:
        text = text.replace('OPENRAZER_PKGREL="1"\n', "")
    pin.write_text(text)
    result, commands = fake.run("--yes", "--version", TAG)
    assert result.returncode != 0
    assert "invalid release manifest/source pin" in result.stderr
    assert not any(
        operation_name(command) in {"sudo", "systemctl", "bsdtar"} for command in commands
    )


@pytest.mark.parametrize(
    "problem",
    [
        "name",
        "version",
        "arch",
        "stamp",
        "missing-stamp",
        "duplicate-member",
        "duplicate-name",
        "linked-version",
        "unbounded-python",
        "mixed-python",
        "malformed-python",
    ],
)
def test_invalid_archive_metadata_blocks_sudo(tmp_path: Path, problem: str) -> None:
    fake = harness(tmp_path)
    metadata = fake.metadata()
    item = metadata[NAMES[1]]
    if problem == "name":
        item["pkginfo"] = item["pkginfo"].replace(ROLES[1], "wrong-package")
    elif problem == "version":
        item["pkginfo"] = item["pkginfo"].replace("fix2", "fix1")
    elif problem == "arch":
        item["pkginfo"] = item["pkginfo"].replace("arch = any", "arch = x86_64")
    elif problem == "stamp":
        item["stamp"] = "a" * 40 + "\n"
    elif problem == "missing-stamp":
        item["members"].remove(f"usr/share/doc/{ROLES[1]}/source-commit")
    elif problem == "duplicate-member":
        item["members"].append("./.PKGINFO")
    elif problem == "duplicate-name":
        item["pkginfo"] += f"pkgname = {ROLES[1]}\n"
    elif problem == "linked-version":
        item["pkginfo"] = item["pkginfo"].replace(f"{ROLES[0]}=", f"{ROLES[0]}>=")
    elif problem == "unbounded-python":
        item["pkginfo"] = item["pkginfo"].replace("depend = python<3.15\n", "")
    elif problem == "mixed-python":
        item["pkginfo"] = item["pkginfo"].replace("3.14", "3.12").replace("3.15", "3.13")
    else:
        item["pkginfo"] = item["pkginfo"].replace("python>=3.14", "python>=bad")
    fake.configure(metadata=metadata)
    result, commands = fake.run("--yes", "--version", TAG)
    assert result.returncode != 0
    assert "invalid package metadata or host Python" in result.stderr
    assert not any(operation_name(command) in {"sudo", "systemctl"} for command in commands)


@pytest.mark.parametrize("host", ["3.12", "3.13", "3.15", "4.14", "invalid"])
def test_host_python_range_checked_before_sudo(tmp_path: Path, host: str) -> None:
    fake = harness(tmp_path)
    fake.configure(host_python=host)
    result, commands = fake.run("--yes", "--version", TAG)
    assert result.returncode != 0
    assert "host Python" in result.stderr
    assert not any(operation_name(command) in {"sudo", "systemctl"} for command in commands)


@pytest.mark.parametrize("failure", ["pacman", "daemon-reload", "enable"])
def test_transaction_and_unit_failures_visible_non_success(tmp_path: Path, failure: str) -> None:
    fake = harness(tmp_path)
    if failure == "pacman":
        fake.configure(pacman_failure=1)
    else:
        fake.configure(unit_failure=failure)
    result, commands = fake.run("--yes", "--version", TAG)
    assert result.returncode != 0
    assert "failed" in result.stderr
    assert "Packages installed; activation DEFERRED" not in result.stdout
    assert not any("restart" in command or "--now" in command for command in commands)


@pytest.mark.parametrize("executable", ["pacman", "bsdtar", "system-python3"])
def test_missing_required_executable_fails_without_privilege(
    tmp_path: Path, executable: str
) -> None:
    fake = harness(tmp_path)
    (Path(fake.environment["PATH"]) / executable).unlink()
    result, commands = fake.run("--yes", "--version", TAG)
    assert result.returncode != 0
    expected = str(fake.system_python) if executable == "system-python3" else executable
    assert expected + " is required" in result.stderr
    assert not any(command[0] in {"curl", "sudo", "systemctl"} for command in commands)
