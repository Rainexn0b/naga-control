from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from buildpython.openrazer_packages import validation
from buildpython.openrazer_packages.pin import PACKAGE_NAMES, package_filenames, read_pin
from scripts import validate_release_assets as release
from tests.release_assets_fakes import (
    PIN_PATH,
    archive_reader,
    checksums,
    package_members,
    write_archive,
    write_assets,
    write_packages,
)


def test_coherent_tiny_archives_validate_and_import_without_hardware(tmp_path: Path) -> None:
    pin = read_pin(PIN_PATH)
    write_packages(tmp_path, pin)
    assert (
        len(validation.validate_packages(tmp_path, pin, imports=True, reader=archive_reader)) == 4
    )


def test_archive_tool_reads_only_listing_or_named_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin = read_pin(PIN_PATH)
    path = tmp_path / package_filenames(pin)[0]
    write_archive(path, package_members(PACKAGE_NAMES[0], pin))
    commands: list[list[str]] = []

    def tool(
        command: list[str], *, check: bool, capture_output: bool
    ) -> subprocess.CompletedProcess[bytes]:
        assert check and capture_output
        commands.append(command)
        if command[1] == "-tf":
            data = archive_reader(Path(command[2]), None)
        else:
            assert command[1] == "-xOf" and command[3] == "--"
            data = archive_reader(Path(command[2]), command[4])
        return subprocess.CompletedProcess(command, 0, stdout=data)

    monkeypatch.setattr(validation.subprocess, "run", tool)
    validation.validate_package(path, PACKAGE_NAMES[0], pin)
    assert commands[0] == ["bsdtar", "-tf", str(path)]
    assert all(command[1] in ("-tf", "-xOf") for command in commands)


@pytest.mark.parametrize(
    "change", ["source", "name", "version", "arch", "dependency", "python", "path", "provenance"]
)
def test_archive_metadata_mismatch_rejected(tmp_path: Path, change: str) -> None:
    pin = read_pin(PIN_PATH)
    write_packages(tmp_path, pin)
    name = PACKAGE_NAMES[1]
    members = package_members(name, pin)
    if change == "source":
        members[f"usr/share/doc/{name}/source-commit"] = b"wrong\n"
    elif change == "dependency":
        members[".PKGINFO"] = members[".PKGINFO"].replace(
            b"openrazer-driver-dkms-local=", b"openrazer-driver-dkms-local>="
        )
    elif change == "python":
        members[".PKGINFO"] = members[".PKGINFO"].replace(
            b"depend = python<", b"depend = unrelated<"
        )
    elif change == "path":
        key = next(key for key in members if key.endswith("/__init__.py"))
        members[key.replace("/site-packages/", "/wrong/")] = members.pop(key)
    elif change == "provenance":
        del members[".BUILDINFO"]
    else:
        field = {"name": b"pkgname", "version": b"pkgver", "arch": b"arch"}[change]
        members[".PKGINFO"] += field + b" = wrong\n"
    write_archive(tmp_path / package_filenames(pin)[1], members)
    checksums(tmp_path, pin)
    with pytest.raises(ValueError):
        validation.validate_packages(tmp_path, pin, reader=archive_reader)


@pytest.mark.parametrize(
    "deps",
    [
        [],
        ["python>=3.14"],
        ["python>=3.14", "python<3.16"],
        ["python>=3.14.1", "python<3.15"],
        ["python>=3.14", "python<3.15", "python<3.15"],
    ],
)
def test_rejects_missing_or_non_minor_python_ranges(deps: list[str]) -> None:
    with pytest.raises(ValueError):
        validation.python_minor({"depend": deps})


def test_python_bounds_and_install_path_must_agree(tmp_path: Path) -> None:
    pin = read_pin(PIN_PATH)
    members = package_members(PACKAGE_NAMES[1], pin, "3.14")
    members["usr/lib/python3.13/site-packages/extra.py"] = b""
    path = tmp_path / package_filenames(pin)[1]
    write_archive(path, members)
    with pytest.raises(ValueError, match="path disagrees"):
        validation.validate_package(path, PACKAGE_NAMES[1], pin, archive_reader)


def test_python_packages_cannot_disagree_on_builder_minor(tmp_path: Path) -> None:
    pin = read_pin(PIN_PATH)
    write_packages(tmp_path, pin)
    different = f"3.{sys.version_info.minor + 1}"
    write_archive(
        tmp_path / package_filenames(pin)[2], package_members(PACKAGE_NAMES[2], pin, different)
    )
    checksums(tmp_path, pin)
    with pytest.raises(ValueError, match="disagree"):
        validation.validate_packages(tmp_path, pin, reader=archive_reader)


@pytest.mark.parametrize(
    "member",
    ["../evil", "/absolute", "a/../../evil", "a\\evil", "a//evil", "a/./evil", "bad\tname"],
)
def test_no_unsafe_archive_paths_are_staged(tmp_path: Path, member: str) -> None:
    pin = read_pin(PIN_PATH)
    members = package_members(PACKAGE_NAMES[2], pin)
    members[member] = b"unsafe"
    path = tmp_path / package_filenames(pin)[2]
    write_archive(path, members)
    with pytest.raises(ValueError, match="Unsafe"):
        validation.validate_package(path, PACKAGE_NAMES[2], pin, archive_reader)


def test_duplicate_archive_member_rejected(tmp_path: Path) -> None:
    def reader(path: Path, member: str | None) -> bytes:
        return b".PKGINFO\n./.PKGINFO\n"

    with pytest.raises(ValueError, match="duplicate"):
        validation.archive_members(tmp_path / "fake", reader)


@pytest.mark.parametrize(
    "change", ["missing", "extra", "hash", "version", "binary", "traversal", "duplicate", "four"]
)
def test_sidecar_and_file_set_strictness(tmp_path: Path, change: str) -> None:
    pin = read_pin(PIN_PATH)
    write_packages(tmp_path, pin)
    path = tmp_path / validation.SIDECAR
    text = path.read_text()
    lines = text.splitlines(keepends=True)
    if change == "missing":
        path.write_text("".join(lines[:-1]))
    elif change == "extra":
        (tmp_path / "old-version.pkg.tar.zst").write_bytes(b"old")
    elif change == "hash":
        (tmp_path / package_filenames(pin)[0]).write_bytes(b"corrupt")
    elif change == "version":
        path.write_text(text.replace("fix2-1-any", "fix1-1-any"))
    elif change == "binary":
        path.write_text(text.replace("  ", " *"))
    elif change == "traversal":
        path.write_text(text.replace("  openrazer", "  ../openrazer"))
    elif change == "duplicate":
        path.write_text(lines[0] + lines[0] + lines[2])
    else:
        path.write_text(text + lines[0])
    with pytest.raises(ValueError):
        validation.validate_packages(tmp_path, pin, reader=archive_reader)


def patch_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    def packages(directory: Path, pin: dict[str, str]) -> tuple[Path, ...]:
        return validation.validate_packages(directory, pin, reader=archive_reader)

    monkeypatch.setattr(release, "validate_packages", packages)


def test_complete_release_set_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    patch_reader(monkeypatch)
    write_assets(tmp_path, read_pin(PIN_PATH))
    assert len(release.validate_release_assets(tmp_path, PIN_PATH)) == 6
    (tmp_path / "old.AppImage").write_bytes(b"old")
    with pytest.raises(ValueError, match="exactly"):
        release.validate_release_assets(tmp_path, PIN_PATH)


@pytest.mark.parametrize("corruption", ["missing", "bytes", "checksum", "symlink"])
def test_bad_appimage_prevents_publication_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    patch_reader(monkeypatch)
    write_assets(tmp_path, read_pin(PIN_PATH))
    image = tmp_path / release.APPIMAGE
    if corruption == "missing":
        image.unlink()
    elif corruption == "bytes":
        image.write_bytes(b"different")
    elif corruption == "checksum":
        (tmp_path / (release.APPIMAGE + ".sha256")).write_text("malformed\n")
    else:
        target = tmp_path / "real-image"
        image.rename(target)
        image.symlink_to(target)
    with pytest.raises(ValueError):
        release.validate_release_assets(tmp_path, PIN_PATH)
