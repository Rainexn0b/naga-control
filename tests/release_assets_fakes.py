"""Tiny fake Arch archives; no network, package install or real OpenRazer imports."""

from __future__ import annotations

import io
import shutil
import sys
import tarfile
from pathlib import Path

from buildpython.openrazer_packages.pin import PACKAGE_NAMES, package_filenames, package_version
from buildpython.openrazer_packages.validation import SIDECAR, sha256

ROOT = Path(__file__).resolve().parents[1]
PIN_PATH = ROOT / "buildpython/openrazer_packages/pin.conf"


def write_project(directory: Path, version: str = "0.4.0") -> None:
    (directory / "buildpython/openrazer_packages").mkdir(parents=True)
    shutil.copyfile(PIN_PATH, directory / "buildpython/openrazer_packages/pin.conf")
    (directory / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n')
    (directory / "changelog.md").write_text(f"## [{version}] - 2026-10-07\n\n- Fixture changes.\n")


def write_archive(path: Path, members: dict[str, bytes]) -> None:
    # Uncompressed tiny tar with the package filename: the injected reader detects format.
    with tarfile.open(path, "w") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


def archive_reader(path: Path, member: str | None) -> bytes:
    with tarfile.open(path) as archive:
        if member is None:
            return ("\n".join(archive.getnames()) + "\n").encode()
        source = archive.extractfile(member)
        assert source is not None
        return source.read()


def package_members(name: str, pin: dict[str, str], minor: str | None = None) -> dict[str, bytes]:
    minor = minor or f"{sys.version_info.major}.{sys.version_info.minor}"
    index = PACKAGE_NAMES.index(name)
    info = f"pkgname = {name}\npkgver = {package_version(pin)}\narch = any\n"
    members = {
        ".BUILDINFO": b"buildenv = fixture\n",
        f"usr/share/doc/{name}/source-commit": (pin["OPENRAZER_COMMIT"] + "\n").encode(),
    }
    if index > 0:
        info += f"depend = {PACKAGE_NAMES[index - 1]}={package_version(pin)}\n"
        info += f"depend = python>={minor}\ndepend = python<3.{int(minor.split('.')[1]) + 1}\n"
        package = "openrazer_daemon" if index == 1 else "openrazer"
        prefix = f"usr/lib/python{minor}/site-packages/{package}/"
        members[prefix + "__init__.py"] = b"# fake pure Python package\n"
        if index == 2:
            members[prefix + "client.py"] = (
                b"import openrazer_daemon\n"
                b"class DeviceManager:\n"
                b"    def __init__(self): raise AssertionError('must not construct hardware')\n"
            )
    members[".PKGINFO"] = info.encode()
    return members


def write_packages(directory: Path, pin: dict[str, str]) -> None:
    directory.mkdir(exist_ok=True)
    for name, filename in zip(PACKAGE_NAMES, package_filenames(pin), strict=True):
        write_archive(directory / filename, package_members(name, pin))
    checksums(directory, pin)


def checksums(directory: Path, pin: dict[str, str]) -> None:
    (directory / SIDECAR).write_text(
        "".join(f"{sha256(directory / name)}  {name}\n" for name in package_filenames(pin))
    )


def write_assets(directory: Path, pin: dict[str, str]) -> None:
    write_packages(directory, pin)
    image = directory / "Naga-Control-x86_64.AppImage"
    image.write_bytes(b"fixture AppImage, not executable")
    (directory / (image.name + ".sha256")).write_text(f"{sha256(image)}  {image.name}\n")
