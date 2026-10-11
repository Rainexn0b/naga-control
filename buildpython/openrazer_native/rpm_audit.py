"""Bounded RPM metadata allowlists from actual Fedora/SUSE evidence."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from . import recipes
from .validation import Runner

SOURCE_PY_VERSION = "3.12.1"

METAINFO_XML = "io.github.openrazer.openrazer.metainfo.xml"

EGG_FILES: tuple[str, ...] = (
    "PKG-INFO",
    "SOURCES.txt",
    "dependency_links.txt",
    "requires.txt",
    "top_level.txt",
)

# Exact rpmlib generators observed in Fedora 44 / openSUSE Tumbleweed smokes.
# Bounded: no activation, no broad prefixes; unknown generators stay rejected.
KNOWN_RPMLIB: tuple[str, ...] = (
    "rpmlib(CompressedFileNames)",
    "rpmlib(FileDigests)",
    "rpmlib(PartialHardlinkSets)",
    "rpmlib(PayloadFilesHavePrefix)",
    "rpmlib(PayloadIsZstd)",
)

_MAX_BYTES = 32 * 1024 * 1024
_MAX_ENTRIES = 8192


def _is_known_rpmlib(item: str) -> bool:
    return any(item == name or item.startswith(name + " ") for name in KNOWN_RPMLIB)


def egg_info_dir(dist: str, minor: str) -> str:
    return f"{dist}-{SOURCE_PY_VERSION}-py{minor}.egg-info"


def check_requires(actual: set[str], family: str, role: str, version: str, minor: str) -> None:
    expected = set(recipes.rpm_requires(family, role, version, minor))
    for item in actual:
        if _is_known_rpmlib(item):
            continue
        if item in expected:
            continue
        if role == "openrazer-driver-dkms-local" and item in ("/bin/sh", "/usr/bin/sh"):
            continue
        if role == "openrazer-daemon-local" and item in (
            "/usr/bin/python3",
            f"python(abi) = {minor}",
        ):
            continue
        if role == "python-openrazer-local" and item == f"python(abi) = {minor}":
            continue
        raise ValueError("RPM Requires has unexpected entries")
    if expected - actual:
        raise ValueError("RPM Requires lacks expected entries")


def check_provides(actual: set[str], role: str, family: str, minor: str, version: str) -> None:
    upstream = recipes.UPSTREAM_RPM[role]
    if upstream not in actual:
        raise ValueError("RPM Provides must include the upstream role")
    allowed: set[str] = {role, f"{role} = {version}"}
    if role == "openrazer-driver-dkms-local":
        allowed.update(("metainfo()", f"metainfo({METAINFO_XML})"))
    else:
        dist = "openrazer-daemon" if role == "openrazer-daemon-local" else "openrazer"
        allowed.add(f"python{minor}dist({dist}) = {SOURCE_PY_VERSION}")
        allowed.add(f"python3dist({dist}) = {SOURCE_PY_VERSION}")
    for item in actual:
        if _is_known_rpmlib(item) or item in allowed:
            continue
        if item == upstream or item.startswith(upstream + " "):
            continue
        raise ValueError("RPM Provides must be the upstream role only")


def check_conflicts_obsoletes(actual: set[str], role: str, label: str) -> None:
    if actual != {recipes.UPSTREAM_RPM[role]}:
        raise ValueError(f"RPM {label} must be the upstream role only")


def check_scripts(scripts: str, triggers: str, role: str, pkgver: str) -> None:
    if triggers.strip():
        raise ValueError("RPM payload must not contain triggers")
    if role == "openrazer-driver-dkms-local":
        if "getent group openrazer" not in scripts or "groupadd -r openrazer" not in scripts:
            raise ValueError("RPM driver scripts must create the openrazer group")
        if pkgver not in scripts or "dkms" not in scripts or "$1" not in scripts:
            raise ValueError("RPM driver scripts must manage matching DKMS")
    elif scripts.strip():
        raise ValueError("Only the driver RPM may carry scriptlets")
    lowered = scripts.lower()
    for fragment in recipes.FORBIDDEN_SCRIPT_FRAGMENTS:
        if fragment.lower() in lowered:
            raise ValueError(f"RPM scripts contain forbidden fragment: {fragment}")
    if "|| true" in scripts or "|| :" in scripts:
        raise ValueError("RPM scripts must not mask DKMS failures")


def rpm_query(path: Path, args: Sequence[str], runner: Runner) -> str:
    result = runner(["rpm", "-qp", *args, "--", str(path)], None)
    if result.returncode != 0:
        raise ValueError("Unable to query RPM metadata")
    return result.stdout.strip()


def cpio_parse_all(data: bytes) -> dict[str, bytes]:
    if not data or len(data) > _MAX_BYTES:
        raise ValueError("Invalid RPM payload size")
    entries: dict[str, bytes] = {}
    seen: set[str] = set()
    offset = 0
    for _ in range(_MAX_ENTRIES):
        if offset + 110 > len(data):
            raise ValueError("Truncated cpio payload")
        if data[offset : offset + 6] != b"070701":
            raise ValueError("Unsupported cpio format")
        try:
            header = data[offset : offset + 110].decode("ascii")
        except UnicodeDecodeError as error:
            raise ValueError("Invalid cpio header encoding") from error
        if not all(c in "0123456789abcdefABCDEF" for c in header[6:]):
            raise ValueError("Invalid cpio header hex")
        try:
            filesize = int(header[54:62], 16)
            namesize = int(header[94:102], 16)
            mode = int(header[14:22], 16)
        except ValueError as error:
            raise ValueError("Invalid cpio header numbers") from error
        if namesize == 0 or namesize > 4096 or filesize < 0 or filesize > _MAX_BYTES:
            raise ValueError("Invalid cpio entry sizes")
        name_start, name_end = offset + 110, offset + 110 + namesize
        if name_end > len(data):
            raise ValueError("Truncated cpio entry name")
        name_raw = data[name_start:name_end]
        if not name_raw.endswith(b"\0"):
            raise ValueError("Cpio entry name lacks NUL terminator")
        try:
            name = name_raw.split(b"\0")[0].decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("Invalid cpio entry name encoding") from error
        clean = name.removeprefix("./").removeprefix("/").removesuffix("/")
        data_start = name_end + ((-(offset + 110 + namesize)) % 4)
        data_end = data_start + filesize
        if data_end > len(data):
            raise ValueError("Truncated cpio entry content")
        content = data[data_start:data_end]
        filetype = mode & 0o170000
        if filetype == 0o120000 or mode & 0o6000:
            raise ValueError("RPM payload must not contain symlinks/setuid")
        if clean in seen:
            raise ValueError("Duplicate RPM payload member")
        seen.add(clean)
        if name != "TRAILER!!!":
            if filetype == 0o040000:
                pass
            elif filetype == 0o100000:
                entries[clean] = content
            elif clean not in ("", "TRAILER!!!"):
                raise ValueError("RPM payload has unsupported member type")
        else:
            offset = data_end + ((-(data_end)) % 4)
            break
        offset = data_end + ((-(data_end)) % 4)
    else:
        raise ValueError("RPM payload has too many entries")
    return entries
