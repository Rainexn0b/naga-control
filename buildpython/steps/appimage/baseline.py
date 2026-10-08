"""Trusted baseline provider loading; root-confined symlinks, no host fallback."""

from __future__ import annotations

import contextlib
import hashlib
import os
import stat
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from . import abi
from .elf import ElfInfo, Inspector, parse_baseline_provider

BASELINE_DIRS = (
    "lib/x86_64-linux-gnu",
    "usr/lib/x86_64-linux-gnu",
    "lib64",
    "usr/lib64",
    "lib",
    "usr/lib",
)
MAX_LINKS = 40
MAX_DEPTH = 128


@dataclass(frozen=True)
class Provider:
    relative: str
    scope: str
    sha256: str
    info: ElfInfo


def _stamp(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _hash_fd(fd: int) -> str:
    digest = hashlib.sha256()
    off = 0
    while True:
        chunk = os.pread(fd, 1024 * 1024, off)
        if not chunk:
            break
        digest.update(chunk)
        off += len(chunk)
    return digest.hexdigest()


def inspect_baseline_fd(fd: int, header: bytes, hint: str, inspector: Inspector) -> ElfInfo:
    from .elf import inspect_elf

    try:
        return inspect_elf(fd, header, inspector)
    except ValueError as exc:
        if "GLIBC_PRIVATE or unknown" in str(exc) and hint in (
            "libc.so.6",
            "ld-linux-x86-64.so.2",
        ):
            result = inspector(fd)
            if result.exit_code or result.skip_reason or result.stderr:
                raise ValueError("baseline readelf failed") from None
            return parse_baseline_provider(result.stdout, provider_key=hint)
        raise


def _open_within_root(root_fd: int, relative: str, root: Path) -> int:
    """Open final regular file following root-confined symlinks; no host fallback."""
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("baseline path escapes root")
    pending: deque[str] = deque(Path(relative).parts)
    current = os.dup(root_fd)
    ancestors: set[tuple[int, int]] = set()
    try:
        root_stat = os.fstat(current)
        ancestors.add((root_stat.st_dev, root_stat.st_ino))
    except OSError as exc:
        with contextlib.suppress(OSError):
            os.close(current)
        raise ValueError(f"baseline root unavailable ({type(exc).__name__})") from None
    links = 0
    try:
        while pending:
            if len(ancestors) > MAX_DEPTH:
                raise ValueError("baseline directory depth limit exceeded")
            part = pending.popleft()
            if part in ("", "."):
                continue
            if part == "..":
                raise ValueError("baseline path escapes root")
            if "/" in part or "\x00" in part:
                raise ValueError("unsupported baseline path component")
            try:
                info = os.stat(part, dir_fd=current, follow_symlinks=False)
            except FileNotFoundError:
                raise FileNotFoundError(part) from None
            except OSError as exc:
                raise ValueError(f"baseline stat failed ({type(exc).__name__})") from None
            if stat.S_ISLNK(info.st_mode):
                links += 1
                if links > MAX_LINKS:
                    raise ValueError("cyclic or excessively deep baseline symlink")
                try:
                    target = os.readlink(part, dir_fd=current)
                except OSError as exc:
                    raise ValueError(f"baseline readlink failed ({type(exc).__name__})") from None
                target_path = Path(target)
                if target_path.is_absolute():
                    try:
                        rel = target_path.relative_to("/")
                    except ValueError:
                        raise ValueError("baseline symlink escapes root") from None
                    # Reinterpret inside explicit root, never host root.
                    with contextlib.suppress(OSError):
                        os.close(current)
                    current = os.dup(root_fd)
                    try:
                        root_stat = os.fstat(current)
                    except OSError:
                        raise ValueError("baseline root unavailable") from None
                    ancestors = {(root_stat.st_dev, root_stat.st_ino)}
                    pending.extendleft(reversed(rel.parts))
                    if target.endswith("/"):
                        pending.append(".")
                else:
                    parts = list(target_path.parts)
                    if target.endswith(("/", "/.")):
                        parts.append(".")
                    pending.extendleft(reversed(parts))
                continue
            if stat.S_ISDIR(info.st_mode):
                key = (info.st_dev, info.st_ino)
                if key in ancestors:
                    raise ValueError("cyclic baseline directory link")
                try:
                    child = os.open(
                        part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current
                    )
                except OSError as exc:
                    raise ValueError(f"baseline open failed ({type(exc).__name__})") from None
                with contextlib.suppress(OSError):
                    os.close(current)
                current = child
                ancestors.add(key)
                if not pending:
                    raise ValueError("baseline path is a directory, not a file")
                continue
            if stat.S_ISREG(info.st_mode):
                if pending:
                    raise ValueError("baseline traverses a non-directory")
                try:
                    fd = os.open(part, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=current)
                except OSError as exc:
                    raise ValueError(f"baseline open failed ({type(exc).__name__})") from None
                with contextlib.suppress(OSError):
                    os.close(current)
                return fd
            raise ValueError("nonregular baseline payload (device/FIFO/socket) is unsupported")
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(current)
        raise
    with contextlib.suppress(OSError):
        os.close(current)
    raise ValueError("baseline path is a directory, not a file")


class BaselineStore:
    def __init__(self, baseline_root: Path, inspector: Inspector) -> None:
        self.baseline_root = baseline_root
        self.inspector = inspector
        self.cache: dict[tuple[int, int], Provider] = {}
        self.errors: list[str] = []

    def load(self, relative: str) -> Provider | None:
        try:
            root = self.baseline_root.resolve(strict=True)
        except OSError:
            self.errors.append(f"baseline:{relative}: baseline root unavailable")
            return None
        try:
            root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError:
            self.errors.append(f"baseline:{relative}: baseline root unavailable")
            return None
        try:
            try:
                fd = _open_within_root(root_fd, relative, root)
            except FileNotFoundError:
                return None
            except ValueError as exc:
                self.errors.append(f"baseline:{relative}: {exc}")
                return None
            finally:
                with contextlib.suppress(OSError):
                    os.close(root_fd)
        except OSError:
            with contextlib.suppress(OSError):
                os.close(root_fd)
            return None
        try:
            raw = os.fstat(fd)
            if not stat.S_ISREG(raw.st_mode):
                with contextlib.suppress(OSError):
                    os.close(fd)
                return None
            info = _stamp(raw)
            key = (raw.st_dev, raw.st_ino)
            if key in self.cache:
                cached = self.cache[key]
                after_hash = _hash_fd(fd)
                current = _stamp(os.fstat(fd))
                with contextlib.suppress(OSError):
                    os.close(fd)
                if after_hash != cached.sha256 or current != info:
                    self.errors.append(f"baseline:{relative}: provider mutated during read")
                    return None
                return cached
            header = os.pread(fd, 64, 0)
            if len(header) < 64 or not header.startswith(b"\x7fELF"):
                with contextlib.suppress(OSError):
                    os.close(fd)
                return None
            digest = hashlib.sha256()
            off, total, fsize = 0, 0, raw.st_size
            while total < fsize:
                chunk = os.pread(fd, 1024 * 1024, off)
                if not chunk:
                    break
                total += len(chunk)
                if total > abi.MAX_ELF_BYTES:
                    with contextlib.suppress(OSError):
                        os.close(fd)
                    self.errors.append(f"baseline:{relative}: ELF size limit exceeded")
                    return None
                digest.update(chunk)
                off += len(chunk)
            if total != fsize:
                with contextlib.suppress(OSError):
                    os.close(fd)
                self.errors.append(f"baseline:{relative}: provider mutated during read")
                return None
            sha = digest.hexdigest()
            hint = Path(relative).name
            try:
                parsed = inspect_baseline_fd(fd, header, hint, self.inspector)
            except (OSError, ValueError) as exc:
                with contextlib.suppress(OSError):
                    os.close(fd)
                msg = (
                    str(exc)
                    if isinstance(exc, ValueError)
                    else f"readelf unavailable ({type(exc).__name__})"
                )
                self.errors.append(f"baseline:{relative}: unreadable provider ({msg})")
                return None
            if _stamp(os.fstat(fd)) != info:
                with contextlib.suppress(OSError):
                    os.close(fd)
                self.errors.append(f"baseline:{relative}: provider mutated during read")
                return None
            provider = Provider(relative, "baseline", sha, parsed)
            self.cache[key] = provider
            with contextlib.suppress(OSError):
                os.close(fd)
            return provider
        except OSError:
            with contextlib.suppress(OSError):
                os.close(fd)
            return None
