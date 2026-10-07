"""Installer/release validator interop on tiny real fixture tar archives only."""

import shutil
from pathlib import Path

import pytest

from buildpython.openrazer_packages.pin import read_pin
from buildpython.openrazer_packages.validation import validate_packages
from tests.openrazer_installer_fakes import NAMES, ROLES, TAG, harness, operation_name
from tests.release_assets_fakes import checksums, package_members, write_archive


@pytest.mark.parametrize(
    "problem",
    [
        None,
        "prefixed",
        "missing-buildinfo",
        "missing-init",
        "wrong-minor",
        "extra-minor",
        "unsafe-path",
        "control-path",
        "duplicate",
        "stamp-crlf",
    ],
)
def test_install_and_release_validation_agree_on_real_fixture_archives(
    tmp_path: Path, problem: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = harness(tmp_path)
    pin = read_pin(fake.remote / "pin.conf")
    real_bsdtar = shutil.which("bsdtar")
    assert real_bsdtar is not None, "bsdtar is required for the read-only fixture interop test"
    fake_bsdtar = Path(fake.environment["PATH"]) / "bsdtar"
    fake_bsdtar.unlink()
    fake_bsdtar.symlink_to(real_bsdtar)
    monkeypatch.setenv("PATH", fake.environment["PATH"])
    for role, name in zip(ROLES, NAMES, strict=True):
        members = package_members(role, pin, minor="3.14")
        if role == ROLES[1]:
            init = "usr/lib/python3.14/site-packages/openrazer_daemon/__init__.py"
            if problem == "missing-buildinfo":
                members.pop(".BUILDINFO")
            elif problem == "missing-init":
                members.pop(init)
            elif problem == "wrong-minor":
                members[init.replace("3.14", "3.13")] = members.pop(init)
            elif problem == "extra-minor":
                members["usr/lib/python3.13/site-packages/other.py"] = b"# wrong minor\n"
            elif problem == "unsafe-path":
                members["../fixture-never-extracted"] = b"unsafe\n"
            elif problem == "control-path":
                members["usr/control\rchar"] = b"unsafe\n"
            elif problem == "duplicate":
                members["./.BUILDINFO"] = b"duplicate normalized member\n"
            elif problem == "stamp-crlf":
                members[f"usr/share/doc/{role}/source-commit"] = (
                    pin["OPENRAZER_COMMIT"] + "\r\n"
                ).encode()
        if problem == "prefixed":
            members = {"./" + name: data for name, data in members.items()}
            members["./usr/"] = b""
        write_archive(fake.remote / name, members)
    checksums(fake.remote, pin)
    accepted = problem in {None, "prefixed"}
    if accepted:
        validate_packages(fake.remote, pin)
    else:
        with pytest.raises(ValueError):
            validate_packages(fake.remote, pin)
    # Only bsdtar reads the fixture archives; interpreter, network, inventory,
    # privilege and unit operations remain hermetic fakes. No payload is executed.
    result, commands = fake.run("--yes", "--version", TAG)
    assert (result.returncode == 0) == accepted, result.stderr
    assert not any(command[0] in {"python", "python3"} for command in commands)
    if accepted:
        assert any(command[:2] == ["sudo", "pacman"] for command in commands)
    else:
        assert "invalid package metadata or host Python" in result.stderr
        assert not any(operation_name(command) in {"sudo", "systemctl"} for command in commands)
