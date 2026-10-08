"""Finished Type2 AppImage static runtime-ABI gate; never executes the artifact."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from ...utils.subproc import RunResult
from . import abi
from .dependencies import Closure, check_closure
from .elf import Inspector, glibc_version, inspect_elf, readelf
from .extraction import MAX_OUTPUT as EXTRACT_MAX
from .extraction import UNSQUASHFS, run_trusted_extractor, staging_base

MAX_APPIMAGE_BYTES = 512 * 1024 * 1024
SQUASH_MAGIC = b"hsqs"
ABSENT = 0xFFFFFFFFFFFFFFFF
BASELINE = "Ubuntu 22.04 / glibc 2.35 / x86_64"
SCOPE = "finished-appimage/static-runtime-abi"
LIMITATIONS = (
    "ELF/glibc/provider closure only; CPU ISA features not evaluated",
    "dlopened or unlisted runtime loads not evaluated",
    "No desktop, hardware, OpenRazer, or provenance acceptance",
    "Native ar archives unsupported; inventory is incomplete",
    "Extraction outside-write check is post-hoc, not a security barrier",
)
Extractor = Callable[[int, int, Path], RunResult]


@dataclass(frozen=True)
class GateReport:
    status: str
    scope: str
    baseline: str
    artifact: Mapping[str, object]
    checked: int
    payloads: tuple[Mapping[str, object], ...]
    providers_checked: bool
    errors: tuple[str, ...]
    unvalidated: tuple[str, ...] = LIMITATIONS


def _runtime_end(header: bytes, file_size: int) -> int:
    if len(header) < 64 or header[:4] != b"\x7fELF" or header[4] != 2:
        raise ValueError("not a Type2 AppImage (missing ELF64LE/AI02 identity)")
    if header[5] != 1 or header[8:11] != b"AI\x02":
        raise ValueError("not a Type2 AppImage (missing ELF64LE/AI02 identity)")
    phoff = int.from_bytes(header[32:40], "little")
    shoff = int.from_bytes(header[40:48], "little")
    phentsize = int.from_bytes(header[54:56], "little")
    phnum = int.from_bytes(header[56:58], "little")
    shentsize = int.from_bytes(header[58:60], "little")
    shnum = int.from_bytes(header[60:62], "little")
    if phentsize not in (0, 56) or shentsize not in (0, 64) or phnum > 65535 or shnum > 65535:
        raise ValueError("invalid ELF header entry sizes")
    ends = [64]
    for off, num, size in ((phoff, phnum, phentsize), (shoff, shnum, shentsize)):
        if num == 0:
            continue
        if off == 0 or off > file_size or size == 0:
            raise ValueError("ELF table out of bounds")
        end = off + num * size
        if end < off or end > file_size:
            raise ValueError("ELF table out of bounds")
        ends.append(end)
    runtime = max(ends)
    if runtime <= 0 or runtime >= file_size:
        raise ValueError("invalid runtime bounds")
    return runtime


def _parse_superblock(data: bytes, offset: int, file_size: int) -> int:
    if len(data) < 96 or data[0:4] != SQUASH_MAGIC:
        raise ValueError("invalid SquashFS superblock magic")
    block_size = int.from_bytes(data[12:16], "little")
    fragments = int.from_bytes(data[16:20], "little")
    compression = int.from_bytes(data[20:22], "little")
    block_log = int.from_bytes(data[22:24], "little")
    if block_size not in (4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288, 1048576):
        raise ValueError("corrupt SquashFS geometry (block size)")
    if not 1 <= compression <= 6 or not 12 <= block_log <= 20:
        raise ValueError("corrupt SquashFS geometry (compression/log)")
    if (1 << block_log) != block_size:
        raise ValueError("corrupt SquashFS geometry (block log)")
    if int.from_bytes(data[28:30], "little") != 4 or int.from_bytes(data[30:32], "little") != 0:
        raise ValueError("unsupported SquashFS version (need v4.0)")
    bytes_used = int.from_bytes(data[40:48], "little")
    if bytes_used <= 96 or offset + bytes_used > file_size or offset + 96 > file_size:
        raise ValueError("SquashFS filesystem out of bounds or truncated")
    tables = {
        48: "id",
        56: "xattr",
        64: "inode",
        72: "directory",
        80: "fragment",
        88: "export",
    }
    for start, kind in tables.items():
        table = int.from_bytes(data[start : start + 8], "little")
        if kind in ("inode", "directory"):
            if table == ABSENT or not 96 <= table < bytes_used:
                raise ValueError(f"corrupt SquashFS geometry ({kind} table out of range)")
            continue
        if table == ABSENT:
            if kind == "fragment" and fragments != 0:
                raise ValueError("corrupt SquashFS geometry (fragment table absent)")
            continue
        if not 96 <= table < bytes_used:
            raise ValueError(f"corrupt SquashFS geometry ({kind} table out of range)")
    return bytes_used


def find_squashfs_offset(fd: int, file_size: int, runtime_end: int) -> int:
    if file_size > MAX_APPIMAGE_BYTES or file_size < 160:
        raise ValueError("artifact size out of bounds")
    if runtime_end <= 0 or runtime_end >= file_size:
        raise ValueError("invalid runtime bounds")
    seen: set[int] = set()
    chunk, overlap, offset, carry, carry_off = 1024 * 1024, 96, runtime_end, b"", runtime_end
    while offset < file_size:
        size = min(chunk, file_size - offset)
        try:
            data = os.pread(fd, size, offset)
        except OSError as exc:
            raise ValueError(f"artifact read failed ({type(exc).__name__})") from None
        if len(data) != size:
            raise ValueError("truncated artifact read")
        window, base, start = carry + data, carry_off, 0
        while True:
            idx = window.find(SQUASH_MAGIC, start)
            if idx < 0:
                break
            cand = base + idx
            if cand < runtime_end or cand + 96 > file_size:
                start = idx + 1
                continue
            if cand in seen:
                start = idx + 1
                continue
            try:
                raw = os.pread(fd, 96, cand)
            except OSError as exc:
                raise ValueError(f"artifact read failed ({type(exc).__name__})") from None
            if len(raw) != 96:
                raise ValueError("truncated SquashFS superblock")
            try:
                _parse_superblock(raw, cand, file_size)
            except ValueError:
                start = idx + 1
                continue
            seen.add(cand)
            if len(seen) > 1:
                raise ValueError("multiple SquashFS superblocks")
            start = idx + 1
        carry = window[-overlap:] if len(window) >= overlap else window
        carry_off = offset + size - len(carry)
        offset += size
    if not seen:
        raise ValueError("no valid SquashFS v4 superblock")
    only = next(iter(seen))
    if only == 0:
        raise ValueError("invalid SquashFS offset")
    return only


def hash_held(fd: int, file_size: int) -> str:
    if file_size > MAX_APPIMAGE_BYTES or file_size <= 0:
        raise ValueError("artifact size limit exceeded")
    digest, off, remaining = hashlib.sha256(), 0, file_size
    while remaining > 0:
        size = min(1024 * 1024, remaining)
        try:
            data = os.pread(fd, size, off)
        except OSError as exc:
            raise ValueError(f"artifact read failed ({type(exc).__name__})") from None
        if len(data) != size:
            raise ValueError("truncated artifact read")
        digest.update(data)
        remaining -= size
        off += size
    return digest.hexdigest()


def _fail(errors: list[str], artifact: Mapping[str, object]) -> GateReport:
    return GateReport("fail", SCOPE, BASELINE, artifact, 0, (), False, tuple(sorted(set(errors))))


def audit_artifact(
    artifact_path: Path,
    baseline_root: Path,
    *,
    inspector: Inspector | None = None,
    extractor: Extractor | None = None,
) -> GateReport:
    inspector = inspector or readelf
    extractor = extractor or run_trusted_extractor
    empty: dict[str, object] = {"name": artifact_path.name, "sha256": "", "size": 0}
    try:
        initial = artifact_path.lstat()
    except OSError as exc:
        return _fail([f"{artifact_path.name}: artifact unavailable ({type(exc).__name__})"], empty)
    if not stat.S_ISREG(initial.st_mode) or artifact_path.is_symlink():
        return _fail([f"{artifact_path.name}: artifact must be a regular file"], empty)
    try:
        baseline_initial = baseline_root.lstat()
    except OSError as exc:
        return _fail([f"{artifact_path.name}: baseline unavailable ({type(exc).__name__})"], empty)
    if not stat.S_ISDIR(baseline_initial.st_mode) or baseline_root.is_symlink():
        return _fail([f"{artifact_path.name}: baseline root must be a directory"], empty)
    if os.geteuid() == 0:
        return _fail([f"{artifact_path.name}: extractor refuses root"], empty)
    if extractor is run_trusted_extractor and not Path(UNSQUASHFS).is_file():
        return _fail([f"{artifact_path.name}: missing extractor {UNSQUASHFS}"], empty)
    staging_parent: Path | None = None
    try:
        fd = os.open(artifact_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        return _fail([f"{artifact_path.name}: artifact open failed ({type(exc).__name__})"], empty)
    errors: list[str] = []
    try:
        live = os.fstat(fd)
        if (live.st_dev, live.st_ino) != (initial.st_dev, initial.st_ino):
            return _fail([f"{artifact_path.name}: artifact changed before read"], empty)
        file_size = live.st_size
        if file_size <= 0 or file_size > MAX_APPIMAGE_BYTES:
            return _fail([f"{artifact_path.name}: artifact size out of bounds"], empty)
        try:
            header = os.pread(fd, 64, 0)
        except OSError as exc:
            return _fail(
                [f"{artifact_path.name}: artifact read failed ({type(exc).__name__})"], empty
            )
        if len(header) != 64:
            return _fail([f"{artifact_path.name}: truncated ELF header"], empty)
        try:
            runtime_end = _runtime_end(header, file_size)
        except ValueError as exc:
            return _fail([f"{artifact_path.name}: {exc}"], empty)
        try:
            outer = inspect_elf(fd, header, inspector)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            msg = (
                str(exc)
                if isinstance(exc, ValueError)
                else f"readelf unavailable ({type(exc).__name__})"
            )
            return _fail([f"{artifact_path.name}: outer inspection failed ({msg})"], empty)
        if outer.elf_type not in ("DYN", "EXEC"):
            return _fail([f"{artifact_path.name}: unsupported outer type"], empty)
        if outer.interpreter is not None and outer.interpreter != abi.LOADER:
            return _fail([f"{artifact_path.name}: unsupported outer interpreter"], empty)
        for name in outer.required_glibc:
            try:
                if glibc_version(name) > (2, 35):
                    return _fail(
                        [f"{artifact_path.name}: {name} exceeds GLIBC_2.35 baseline"], empty
                    )
            except ValueError as exc:
                return _fail([f"{artifact_path.name}: outer inspection failed ({exc})"], empty)
        try:
            before_sha = hash_held(fd, file_size)
        except ValueError as exc:
            return _fail([f"{artifact_path.name}: {exc}"], empty)
        try:
            squash_offset = find_squashfs_offset(fd, file_size, runtime_end)
        except ValueError as exc:
            return _fail([f"{artifact_path.name}: {exc}"], empty)
        try:
            base = staging_base()
            base.mkdir(parents=True, exist_ok=True)
            staging_parent = Path(tempfile.mkdtemp(prefix="artifact-gate.", dir=str(base)))
            os.chmod(staging_parent, 0o700)
            staging = staging_parent / "root"
            staging.mkdir(mode=0o700)
        except OSError as exc:
            meta = {"name": artifact_path.name, "sha256": before_sha, "size": file_size}
            return _fail(
                [f"{artifact_path.name}: scratch unavailable ({type(exc).__name__})"], meta
            )
        result = extractor(fd, squash_offset, staging)
        if result.exit_code or result.skip_reason:
            errors.append(f"{artifact_path.name}: extraction failed ({result.stderr[:200]})")
        if len(result.stdout.encode()) > EXTRACT_MAX or len(result.stderr.encode()) > EXTRACT_MAX:
            errors.append(f"{artifact_path.name}: extractor output limit exceeded")
        if os.fstat(fd).st_ino != live.st_ino or os.fstat(fd).st_dev != live.st_dev:
            errors.append(f"{artifact_path.name}: artifact mutated during extraction")
        else:
            try:
                after_sha = hash_held(fd, file_size)
            except ValueError as exc:
                errors.append(f"{artifact_path.name}: {exc}")
            else:
                if after_sha != before_sha or os.fstat(fd).st_size != file_size:
                    errors.append(f"{artifact_path.name}: artifact mutated during extraction")
        with contextlib.suppress(OSError):
            names = sorted(os.listdir(staging_parent))
            if names != ["root"]:
                errors.append(f"{artifact_path.name}: extractor wrote outside staging")
        if errors:
            meta = {
                "name": artifact_path.name,
                "sha256": before_sha,
                "size": file_size,
                "squashfs_offset": squash_offset,
            }
            try:
                shutil.rmtree(staging_parent)
            except OSError as exc:
                errors.append(f"{artifact_path.name}: scratch cleanup failed ({exc})")
                staging_parent = None
                return GateReport(
                    "fail", SCOPE, BASELINE, meta, 0, (), False, tuple(sorted(set(errors)))
                )
            staging_parent = None
            return GateReport(
                "fail", SCOPE, BASELINE, meta, 0, (), False, tuple(sorted(set(errors)))
            )
        report = abi.audit(staging, inspector=inspector)
        payload_dicts = tuple({"paths": list(p.paths), "sha256": p.sha256} for p in report.payloads)
        meta = {
            "name": artifact_path.name,
            "sha256": before_sha,
            "size": file_size,
            "squashfs_offset": squash_offset,
        }
        combined = list(report.errors)
        if not report.inventory_complete:
            combined.append(f"{artifact_path.name}: extraction inventory incomplete")
        if not any(p.elf is not None for p in report.payloads):
            combined.append(f"{artifact_path.name}: no successfully inspected ELF payloads")
        if outer.needed_libraries:
            outer_closure = Closure(Path("."), (), baseline_root, inspector)
            outer_closure.check_object(artifact_path.name, outer, ".", 0)
            combined.extend(outer_closure.errors)
        if report.payloads:
            combined.extend(check_closure(staging, report.payloads, baseline_root, inspector))
        try:
            shutil.rmtree(staging_parent)
        except OSError as exc:
            combined.append(f"{artifact_path.name}: scratch cleanup failed ({exc})")
        staging_parent = None
        if combined:
            return GateReport(
                "fail",
                SCOPE,
                BASELINE,
                meta,
                len(report.payloads),
                payload_dicts,
                True,
                tuple(sorted(set(combined))),
            )
        return GateReport(
            "pass", SCOPE, BASELINE, meta, len(report.payloads), payload_dicts, True, ()
        )
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)
        if staging_parent is not None:
            with contextlib.suppress(OSError):
                shutil.rmtree(staging_parent, ignore_errors=False)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("appimage", type=Path, help="finished Type2 AppImage file")
    parser.add_argument("--baseline-root", required=True, type=Path)
    args = parser.parse_args(argv)
    report = audit_artifact(args.appimage, args.baseline_root)
    print(json.dumps(asdict(report), ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return 0 if report.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
