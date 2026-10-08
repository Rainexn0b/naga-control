"""Read-only preliminary staged-AppDir ELF/glibc audit, not an ABI release gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
from collections import deque
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .elf import ElfInfo, Inspector, glibc_version, inspect_elf, readelf

MAX_ENTRIES = 100_000
MAX_ELF_BYTES = 512 * 1024 * 1024
LOADER = "/lib64/ld-linux-x86-64.so.2"
LIMITATIONS = (
    "ELF/glibc requirements check only; final AppImage runtime/payload, "
    "DT_NEEDED/provider closure, GLIBCXX/CXXABI/provider and runtime loads not accepted",
    "GNU notes/CPU ISA feature compatibility not evaluated",
    "No immutable filesystem, build provenance, or publication acceptance",
)
Stamp = tuple[int, int, int, int, int, int]


@dataclass(frozen=True)
class Payload:
    paths: tuple[str, ...]
    sha256: str
    elf: ElfInfo | None


@dataclass(frozen=True)
class AuditReport:
    status: str
    inventory_complete: bool
    payloads: tuple[Payload, ...]
    errors: tuple[str, ...]
    scope: str = "staged-appdir/preliminary"
    baseline: str = "Ubuntu 22.04 / glibc 2.35 / x86_64"
    unvalidated: tuple[str, ...] = LIMITATIONS


@dataclass
class FileEntry:
    relative: str
    stamp: Stamp
    paths: list[str] = field(default_factory=list[str])


def _stamp(info: os.stat_result) -> Stamp:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def open_relative(root_fd: int, relative: str, *, directory: bool = False) -> int:
    """Open only beneath the held root; reject symlinks at every component."""
    parts = Path(relative).parts
    if Path(relative).is_absolute() or ".." in parts:
        raise ValueError("relative open escapes audit root")
    parent = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        if not parts:
            return os.dup(parent)
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        if directory:
            flags |= os.O_DIRECTORY
        return os.open(parts[-1], flags, dir_fd=parent)
    finally:
        os.close(parent)


def _resolve(root_fd: int, relative: str, root: Path) -> tuple[str, os.stat_result]:
    """Resolve links component by component without ever traversing outside root."""
    pending, links = deque(Path(relative).parts), 0
    resolved: list[str] = []
    while pending:
        part = pending.popleft()
        if part in ("", "."):
            continue
        if part == "..":
            if not resolved:
                raise ValueError("symlink escapes audit root")
            resolved.pop()
            continue
        parent = open_relative(root_fd, "/".join(resolved), directory=True)
        try:
            info = os.stat(part, dir_fd=parent, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                links += 1
                if links > 40:
                    raise ValueError("cyclic or excessively deep symlink")
                link = os.readlink(part, dir_fd=parent)
                target = Path(link)
                if target.is_absolute():
                    try:
                        target = target.relative_to(root)
                    except ValueError:
                        raise ValueError("symlink escapes audit root") from None
                    resolved.clear()
                parts = list(target.parts)
                if link.endswith(("/", "/.")):
                    parts.append(".")
                pending.extendleft(reversed(parts))
            else:
                if pending and not stat.S_ISDIR(info.st_mode):
                    raise ValueError("symlink traverses a non-directory")
                resolved.append(part)
        finally:
            os.close(parent)
    relative = "/".join(resolved)
    if not relative:
        return relative, os.fstat(root_fd)
    parent = open_relative(root_fd, str(Path(relative).parent), directory=True)
    try:
        return relative, os.stat(Path(relative).name, dir_fd=parent, follow_symlinks=False)
    finally:
        os.close(parent)


def _scan(
    root_fd: int, root: Path
) -> tuple[list[FileEntry], dict[str, tuple[Stamp, str, Stamp]], list[str]]:
    files: dict[tuple[int, int], FileEntry] = {}
    snapshot = {".": (_stamp(os.fstat(root_fd)), "", _stamp(os.fstat(root_fd)))}
    errors: list[str] = []
    visited = 0

    def walk(logical: str, relative: str, ancestors: set[tuple[int, int]]) -> None:
        nonlocal visited
        if len(ancestors) > 128:
            raise ValueError("inventory directory depth limit exceeded")
        directory_fd = open_relative(root_fd, relative, directory=True)
        try:
            with os.scandir(directory_fd) as entries:
                names: list[str] = []
                for entry in entries:
                    visited += 1
                    if visited > MAX_ENTRIES:
                        raise ValueError("inventory entry limit exceeded")
                    names.append(entry.name)
            for name in sorted(names):
                path = f"{logical}/{name}" if logical else name
                real = f"{relative}/{name}" if relative else name
                try:
                    info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    target = info
                    if stat.S_ISLNK(info.st_mode):
                        real, target = _resolve(root_fd, real, root)
                    snapshot[path] = (_stamp(info), real, _stamp(target))
                    key = (target.st_dev, target.st_ino)
                    if stat.S_ISDIR(target.st_mode):
                        if key in ancestors:
                            raise ValueError("cyclic directory link")
                        walk(path, real, ancestors | {key})
                    elif stat.S_ISREG(target.st_mode):
                        if key not in files:
                            files[key] = FileEntry(real, _stamp(target))
                        if files[key].stamp != _stamp(target):
                            raise ValueError("payload mutated during inventory")
                        files[key].paths.append(path)
                    else:
                        raise ValueError("nonregular payload (device/FIFO/socket) is unsupported")
                except (OSError, ValueError) as exc:
                    message = (
                        str(exc)
                        if isinstance(exc, ValueError)
                        else f"scan failed ({type(exc).__name__})"
                    )
                    errors.append(f"{path}: {message}")
        finally:
            os.close(directory_fd)

    try:
        info = os.fstat(root_fd)
        walk("", "", {(info.st_dev, info.st_ino)})
    except (OSError, ValueError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else f"scan failed ({type(exc).__name__})"
        errors.append(f".: {message}")
    return sorted(files.values(), key=lambda item: item.paths[0]), snapshot, errors


def inspect_payload(
    root_fd: int, item: FileEntry, inspector: Inspector
) -> tuple[Payload | None, str]:
    fd = open_relative(root_fd, item.relative)
    try:
        before = _stamp(os.fstat(fd))
        if before != item.stamp or not stat.S_ISREG(before[2]):
            raise ValueError("payload changed or became nonregular before read")
        header = os.read(fd, 64)
        if header.startswith((b"!<arch>\n", b"!<thin>\n")):
            raise ValueError("native ar archive unsupported; inventory is incomplete")
        if not header.startswith(b"\x7fELF"):
            if _stamp(os.fstat(fd)) != before:
                raise ValueError("payload mutated during read")
            return None, ""
        if before[3] > MAX_ELF_BYTES:
            raise ValueError("ELF size limit exceeded")
        digest, size = hashlib.sha256(header), len(header)
        while chunk := os.read(fd, 1024 * 1024):
            size += len(chunk)
            if size > MAX_ELF_BYTES:
                raise ValueError("ELF size limit exceeded during read")
            digest.update(chunk)
        metadata, error = None, ""
        try:
            metadata = inspect_elf(fd, header, inspector)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            error = (
                str(exc)
                if isinstance(exc, ValueError)
                else f"readelf unavailable ({type(exc).__name__})"
            )
        if size != before[3] or _stamp(os.fstat(fd)) != before:
            raise ValueError("payload mutated during hash/readelf inspection")
        return Payload(tuple(sorted(item.paths)), digest.hexdigest(), metadata), error
    finally:
        os.close(fd)


def _policy(payload: Payload) -> list[str]:
    info = payload.elf
    assert info is not None
    errors: list[str] = []
    if info.interpreter is not None and info.interpreter != LOADER:
        errors.append("unsupported interpreter (expected /lib64/ld-linux-x86-64.so.2)")
    for name in info.required_glibc:
        if glibc_version(name) > (2, 35):
            errors.append(f"{name} exceeds GLIBC_2.35 baseline")
    return [f"{payload.paths[0]}: {error}" for error in errors]


def audit(appdir: Path, *, inspector: Inspector | None = None) -> AuditReport:
    """Scan actual magic, deduplicating inode content while retaining all aliases.

    Before/after metadata checks detect ordinary mutation, not an immutable-FS
    guarantee. Each inspector sees the same held file that was hashed. No staged
    executable, ldd, library import, extraction, or build is used.
    """
    inspector = inspector or readelf
    payloads: list[Payload] = []
    errors: list[str] = []
    complete = True
    root_fd: int | None = None
    try:
        root = appdir.absolute()
        initial = root.lstat()
        if not stat.S_ISDIR(initial.st_mode):
            raise ValueError("audit root must be a directory, not a symlink or special file")
        root = root.resolve(strict=True)
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        if _stamp(os.fstat(root_fd)) != _stamp(initial):
            raise ValueError("audit root changed before scan")
        files, snapshot, scan_errors = _scan(root_fd, root)
        errors.extend(scan_errors)
        complete = not scan_errors
        for item in files:
            try:
                payload, error = inspect_payload(root_fd, item, inspector)
                if payload is not None:
                    payloads.append(payload)
                    if error:
                        complete = False
                        errors.append(f"{item.paths[0]}: {error}")
                    else:
                        errors.extend(_policy(payload))
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                complete = False
                message = (
                    str(exc)
                    if isinstance(exc, ValueError)
                    else f"inspection unavailable ({type(exc).__name__})"
                )
                errors.append(f"{item.paths[0]}: {message}")
        _, final_snapshot, final_errors = _scan(root_fd, root)
        errors.extend(final_errors)
        complete = complete and not final_errors
        if snapshot != final_snapshot or _stamp(root.lstat()) != _stamp(initial):
            complete = False
            errors.append(".: inventory mutated during audit")
        if not any(payload.elf is not None for payload in payloads):
            complete = False
            errors.append(
                ".: no successfully inspected ELF payloads; inventory is empty or incomplete"
            )
    except (OSError, ValueError) as exc:
        complete = False
        message = (
            str(exc)
            if isinstance(exc, ValueError)
            else f"root/scan unavailable ({type(exc).__name__})"
        )
        errors.append(f".: {message}")
    finally:
        if root_fd is not None:
            os.close(root_fd)
    return AuditReport(
        "fail" if errors else "pass", complete, tuple(payloads), tuple(sorted(set(errors)))
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "appdir", type=Path, help="explicit staged AppDir; no extraction or execution"
    )
    args = parser.parse_args(argv)
    report = audit(args.appdir)
    print(json.dumps(asdict(report), ensure_ascii=True, sort_keys=True))
    return 0 if report.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
