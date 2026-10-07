"""Validate one coherent Arch package set, without installing or contacting hardware."""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from .pin import PACKAGE_NAMES, package_filenames, package_version

SIDECAR = "openrazer-arch-packages.sha256"
ArchiveReader = Callable[[Path, str | None], bytes]


def read_archive(path: Path, member: str | None) -> bytes:
    command = (
        ["bsdtar", "-tf", str(path)]
        if member is None
        else ["bsdtar", "-xOf", str(path), "--", member]
    )
    return subprocess.run(command, check=True, capture_output=True).stdout


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def parse_checksums(text: str, expected: tuple[str, ...]) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line in text.splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._+-]*)", line)
        if match is None or match[2] not in expected or match[2] in checksums:
            raise ValueError("Invalid checksum sidecar: unsafe, duplicate or unexpected basename")
        checksums[match[2]] = match[1]
    if set(checksums) != set(expected):
        raise ValueError("Incomplete checksum sidecar")
    return checksums


def archive_members(path: Path, reader: ArchiveReader) -> dict[str, str]:
    members: dict[str, str] = {}
    for raw in reader(path, None).decode("utf-8").splitlines():
        name = raw.removeprefix("./").removesuffix("/")
        if not name:
            continue
        parts = name.split("/")
        if (
            name.startswith("/")
            or any(part in ("", ".", "..") for part in parts)
            or "\\" in name
            or any(ord(char) < 32 or ord(char) == 127 for char in name)
            or name in members
        ):
            raise ValueError("Unsafe or duplicate archive member")
        members[name] = raw
    return members


def metadata(text: str) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        if " = " not in line:
            raise ValueError("Malformed .PKGINFO")
        key, value = line.split(" = ", 1)
        fields.setdefault(key, []).append(value)
    return fields


def python_minor(fields: dict[str, list[str]]) -> str:
    dependencies = fields.get("depend", [])
    lower = [dep for dep in dependencies if dep.startswith("python>=")]
    upper = [dep for dep in dependencies if dep.startswith("python<")]
    if len(lower) != 1 or len(upper) != 1:
        raise ValueError("Missing exact builder Python minor bounds")
    match = re.fullmatch(r"python>=3\.([0-9]+)", lower[0])
    if match is None or upper[0] != f"python<3.{int(match[1]) + 1}":
        raise ValueError("Invalid builder Python minor range")
    return f"3.{int(match[1])}"


def validate_package(
    path: Path, name: str, pin: dict[str, str], reader: ArchiveReader = read_archive
) -> tuple[str | None, dict[str, str]]:
    members = archive_members(path, reader)
    if ".PKGINFO" not in members or ".BUILDINFO" not in members:
        raise ValueError("Missing package metadata/provenance")
    fields = metadata(reader(path, members[".PKGINFO"]).decode("utf-8"))
    for key, expected in (("pkgname", name), ("pkgver", package_version(pin)), ("arch", "any")):
        if fields.get(key) != [expected]:
            raise ValueError(f"Package {key} does not match pin: {path.name}")
    stamp = f"usr/share/doc/{name}/source-commit"
    if stamp not in members or reader(path, members[stamp]) != (
        pin["OPENRAZER_COMMIT"] + "\n"
    ).encode("ascii"):
        raise ValueError("Package source stamp does not match pin")
    index = PACKAGE_NAMES.index(name)
    if index == 0:
        return None, members
    required = f"{PACKAGE_NAMES[index - 1]}={package_version(pin)}"
    deps = fields.get("depend", [])
    family = [dep for dep in deps if dep.startswith(PACKAGE_NAMES[index - 1])]
    if family != [required]:
        raise ValueError("Package dependency does not match exact pinned set")
    minor = python_minor(fields)
    package = "openrazer_daemon" if index == 1 else "openrazer"
    root = f"usr/lib/python{minor}/site-packages/"
    if root + package + "/__init__.py" not in members:
        raise ValueError("Missing Python package at declared builder minor")
    if any(
        member.startswith("usr/lib/python")
        and "/site-packages/" in member
        and not member.startswith(root)
        for member in members
    ):
        raise ValueError("Python installation path disagrees with dependency bounds")
    return minor, members


def check_imports(
    directory: Path, pin: dict[str, str], minor: str, reader: ArchiveReader = read_archive
) -> None:
    if minor != f"{sys.version_info.major}.{sys.version_info.minor}":
        raise ValueError("Import validation must run with the builder Python minor")
    with tempfile.TemporaryDirectory(prefix="openrazer-imports-") as temp:
        stage = Path(temp)
        prefix = f"usr/lib/python{minor}/site-packages/"
        for name, filename in zip(PACKAGE_NAMES[1:], package_filenames(pin)[1:], strict=True):
            path = directory / filename
            _, members = validate_package(path, name, pin, reader)
            package = "openrazer_daemon" if name == PACKAGE_NAMES[1] else "openrazer"
            for member, raw in members.items():
                if member.startswith(prefix + package + "/") and member.endswith(".py"):
                    # Stage bytes, never extract links/paths from an untrusted archive.
                    target = stage / PurePosixPath(member.removeprefix(prefix))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(reader(path, raw))
        code = (
            "import pathlib, sys; sys.path.insert(0, sys.argv[1]); "
            "import openrazer.client, openrazer_daemon; "
            "root = pathlib.Path(sys.argv[1]).resolve(); "
            "assert all(pathlib.Path(m.__file__).resolve().is_relative_to(root) "
            "for m in (openrazer.client, openrazer_daemon)); "
            "print('Clean staged OpenRazer imports passed (no DeviceManager construction)')"
        )
        subprocess.run([sys.executable, "-I", "-c", code, str(stage)], cwd=stage, check=True)


def validate_packages(
    directory: Path,
    pin: dict[str, str],
    *,
    imports: bool = False,
    reader: ArchiveReader = read_archive,
) -> tuple[Path, ...]:
    expected = package_filenames(pin)
    actual = {path.name for path in directory.glob("*.pkg.tar.*")}
    if actual != set(expected):
        raise ValueError("Package directory must contain exactly the pinned three archives")
    sidecar = directory / SIDECAR
    if not sidecar.is_file() or sidecar.is_symlink():
        raise ValueError("Package checksum sidecar must be a regular file")
    checksums = parse_checksums(sidecar.read_text(encoding="ascii"), expected)
    minors: set[str] = set()
    for name, filename in zip(PACKAGE_NAMES, expected, strict=True):
        path = directory / filename
        if not path.is_file() or path.is_symlink() or sha256(path) != checksums[filename]:
            raise ValueError(f"Package hash or file type mismatch: {filename}")
        minor, _ = validate_package(path, name, pin, reader)
        if minor is not None:
            minors.add(minor)
    if len(minors) != 1:
        raise ValueError("Python-bearing packages disagree on builder minor")
    if imports:
        check_imports(directory, pin, minors.pop(), reader)
    return (*(directory / filename for filename in expected), directory / SIDECAR)
