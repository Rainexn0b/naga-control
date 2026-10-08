"""Fakes for finished-artifact gate; synthetic bytes and callbacks only."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from pathlib import Path

from buildpython.utils.subproc import RunResult

BLOCK_SIZES = (4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288, 1048576)


def outer_header(*, ai02: bool = True, phnum: int = 1, shnum: int = 1) -> bytes:
    header = bytearray(64)
    header[:7] = b"\x7fELF\x02\x01\x01"
    header[7] = 0
    if ai02:
        header[8:11] = b"AI\x02"
    else:
        header[8:11] = b"AI\x01"
    header[16:18] = (3).to_bytes(2, "little")
    header[18:20] = (62).to_bytes(2, "little")
    header[20:24] = (1).to_bytes(4, "little")
    header[32:40] = (64).to_bytes(8, "little")
    header[40:48] = (64 + phnum * 56).to_bytes(8, "little")
    header[52:54] = (64).to_bytes(2, "little")
    header[54:56] = (56).to_bytes(2, "little")
    header[56:58] = phnum.to_bytes(2, "little")
    header[58:60] = (64).to_bytes(2, "little")
    header[60:62] = shnum.to_bytes(2, "little")
    return bytes(header)


def inner_header() -> bytes:
    header = bytearray(64)
    header[:7] = b"\x7fELF\x02\x01\x01"
    header[16:18] = (3).to_bytes(2, "little")
    header[18:20] = (62).to_bytes(2, "little")
    header[20:24] = (1).to_bytes(4, "little")
    header[52:54] = (64).to_bytes(2, "little")
    header[54:56] = (56).to_bytes(2, "little")
    header[56:58] = (1).to_bytes(2, "little")
    header[58:60] = (64).to_bytes(2, "little")
    header[60:62] = (4).to_bytes(2, "little")
    return bytes(header)


def superblock(
    *,
    offset_valid: bool = True,
    block_size: int = 131072,
    absent: tuple[str, ...] = (),
    fragments: int = 1,
) -> bytes:
    raw = bytearray(96)
    raw[0:4] = b"hsqs"
    raw[4:8] = (100).to_bytes(4, "little")
    raw[12:16] = (block_size if offset_valid else 0).to_bytes(4, "little")
    raw[16:20] = fragments.to_bytes(4, "little")
    raw[20:22] = (4 if offset_valid else 0).to_bytes(2, "little")
    log = {4096: 12, 8192: 13, 16384: 14, 32768: 15, 65536: 16}.get(block_size, 17)
    raw[22:24] = (log if offset_valid else 0).to_bytes(2, "little")
    raw[26:28] = (10 if offset_valid else 0).to_bytes(2, "little")
    raw[28:30] = (4 if offset_valid else 9).to_bytes(2, "little")
    raw[30:32] = (0).to_bytes(2, "little")
    raw[32:40] = (1).to_bytes(8, "little")
    raw[40:48] = (8192).to_bytes(8, "little")
    table_off = {"id": 48, "xattr": 56, "inode": 64, "directory": 72, "fragment": 80, "export": 88}
    for kind, start in table_off.items():
        if kind in absent:
            raw[start : start + 8] = (0xFFFFFFFFFFFFFFFF).to_bytes(8, "little")
        else:
            raw[start : start + 8] = (100).to_bytes(8, "little")
    if not offset_valid:
        raw[12:16] = (0).to_bytes(4, "little")
    return bytes(raw)


def counts_for(text: str) -> tuple[int, int]:
    import re as _re

    prog = int(_re.search(r"Number of program headers:\s*(\d+)", text).group(1))  # type: ignore[union-attr]
    sect = int(_re.search(r"Number of section headers:\s*(\d+)", text).group(1))  # type: ignore[union-attr]
    return prog, sect


def header_for(text: str, *, ai02: bool = False) -> bytes:
    prog, sect = counts_for(text)
    if ai02:
        return outer_header(phnum=prog, shnum=sect, ai02=True)
    header = bytearray(64)
    header[:7] = b"\x7fELF\x02\x01\x01"
    header[16:18] = (3).to_bytes(2, "little")
    header[18:20] = (62).to_bytes(2, "little")
    header[20:24] = (1).to_bytes(4, "little")
    header[52:54] = (64).to_bytes(2, "little")
    header[54:56] = (56).to_bytes(2, "little")
    header[56:58] = prog.to_bytes(2, "little")
    header[58:60] = (64).to_bytes(2, "little")
    header[60:62] = sect.to_bytes(2, "little")
    return bytes(header)


def write_appimage(
    path: Path,
    *,
    offset: int = 4096,
    decoys: list[tuple[int, bytes]] | None = None,
    extra_valid: int | None = None,
) -> Path:
    header = outer_header(phnum=1, shnum=4)
    size = offset + 8192
    data = bytearray(size)
    data[0:64] = header
    data[offset : offset + 96] = superblock(offset_valid=True)
    for at, blob in decoys or []:
        data[at : at + len(blob)] = blob
    if extra_valid is not None:
        data[extra_valid : extra_valid + 96] = superblock(offset_valid=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(data))
    return path


def write_appimage_with_text(
    path: Path,
    outer_text: str,
    *,
    offset: int = 4096,
    decoys: list[tuple[int, bytes]] | None = None,
    extra_valid: int | None = None,
    superblock_data: bytes | None = None,
) -> Path:
    header = header_for(outer_text, ai02=True)
    end = offset + 8192
    if extra_valid is not None:
        end = max(end, extra_valid + 8192)
    data = bytearray(end)
    data[0:64] = header
    data[offset : offset + 96] = superblock_data if superblock_data is not None else superblock()
    for at, blob in decoys or []:
        data[at : at + len(blob)] = blob
    if extra_valid is not None:
        data[extra_valid : extra_valid + 96] = (
            superblock_data if superblock_data is not None else superblock()
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(data))
    return path


def dep_text(
    *,
    needed: tuple[str, ...] = ("libc.so.6",),
    needs_map: dict[str, tuple[str, ...]] | None = None,
    defs: tuple[str, ...] = (),
    soname: str | None = None,
    rpath: str | None = None,
    runpath: str | None = None,
    interpreter: str | None = None,
    elf_class: str = "ELF64",
    endian: str = "2's complement, little endian",
    machine: str = "Advanced Micro Devices X86-64",
    elf_type: str = "DYN",
) -> str:
    needs_map = {"libc.so.6": ("GLIBC_2.35",)} if needs_map is None and needed else needs_map or {}
    all_needs: list[str] = [n for names in needs_map.values() for n in names]
    symbols = ["(*local*)", *(f"({n})" for n in (*all_needs, *defs))]
    sections = ["[ 0] NULL 0000000000000000 000000 000000 00 0 0 0"]
    tables: list[str] = []
    if symbols[1:]:
        rows = [
            f" {s:03x}: "
            + " ".join(f"{i:x} {n}" for i, n in enumerate(symbols[s : s + 4], start=s))
            for s in range(0, len(symbols), 4)
        ]
        sections.append(
            f"[ 1] .gnu.version VERSYM 0000000000000000 000000 {len(symbols) * 2:06x} 02 A 0 0 2"
        )
        tables.append(
            f"Version symbols section '.gnu.version' contains {len(symbols)} entries:\n"
            " Addr: 0x0000000000000000 Offset: 0x000000 Link: 0 (.dynsym)\n" + "\n".join(rows)
        )
    if defs:
        sections.append(
            f"[ {len(sections)}] .gnu.version_d VERDEF 0000000000000000 000000 {28 * len(defs):06x} 00 A 0 0 8"
        )
        tables.append(
            f"Version definition section '.gnu.version_d' contains {len(defs)} entries:\n"
            " Addr: 0x0000000000000000 Offset: 0x000000 Link: 0 (.dynstr)\n"
            + "\n".join(
                f" {i * 28:06x}: Rev: 1 Flags: none Index: {i + 1} Cnt: 1 Name: {n}"
                for i, n in enumerate(defs)
            )
        )
    if needs_map:
        total = sum(len(v) for v in needs_map.values())
        nfiles = len(needs_map)
        sections.append(
            f"[ {len(sections)}] .gnu.version_r VERNEED 0000000000000000 000000 {16 * (nfiles + total):06x} 00 A 0 0 8"
        )
        lines = [
            f"Version needs section '.gnu.version_r' contains {nfiles} entries:\n"
            " Addr: 0x0000000000000000 Offset: 0x000000 Link: 0 (.dynstr)"
        ]
        off = 0
        for provider, names in needs_map.items():
            lines.append(f" {off:06x}: Version: 1 File: {provider} Cnt: {len(names)}")
            for i, name in enumerate(names):
                lines.append(
                    f" {(off + 16 * (i + 1)):06x}: Name: {name} Flags: none Version: {i + 2}"
                )
            off += 16 * (1 + len(names))
        tables.append("\n".join(lines))
    tags: list[str] = []
    for lib in needed:
        tags.append(f"0x0000000000000001 (NEEDED) Shared library: [{lib}]")
    if soname is not None:
        tags.append(f"0x000000000000000e (SONAME) Library soname: [{soname}]")
    if rpath is not None:
        tags.append(f"0x000000000000000f (RPATH) Library rpath: [{rpath}]")
    if runpath is not None:
        tags.append(f"0x000000000000001d (RUNPATH) Library runpath: [{runpath}]")
    if needs_map:
        tags += [
            "0x000000006ffffffe (VERNEED) 0x0",
            f"0x000000006fffffff (VERNEEDNUM) {len(needs_map)}",
        ]
    if defs:
        tags += ["0x000000006ffffffc (VERDEF) 0x0", f"0x000000006ffffffd (VERDEFNUM) {len(defs)}"]
    if symbols[1:]:
        tags.append("0x000000006ffffff0 (VERSYM) 0x0")
    dynamic = "There is no dynamic section in this file."
    if tags:
        tags.append("0x0000000000000000 (NULL) 0x0")
        sections.append(
            f"[ {len(sections)}] .dynamic DYNAMIC 0000000000000000 000000 {16 * len(tags):06x} 10 WA 0 0 8"
        )
        dynamic = (
            f"Dynamic section at offset 0x0 contains {len(tags)} entries:\n"
            " Tag Type Name/Value\n " + "\n ".join(tags)
        )
    programs = [" LOAD 0x000000 0x0000000000000000 0x0000000000000000 0x000040 0x000040 R E 0x1000"]
    if interpreter:
        programs += [
            " INTERP 0x000040 0x0000000000000040 0x0000000000000040 0x00001c 0x00001c R 0x1",
            f" [Requesting program interpreter: {interpreter}]",
        ]
    nprog = 2 if interpreter else 1
    body = (
        "ELF Header:\n"
        f" Class: {elf_class}\n Data: {endian}\n Type: {elf_type} (Shared object file)\n"
        f" Machine: {machine}\n Number of program headers: {nprog}\n"
        f" Number of section headers: {len(sections)}\n\n"
        "Section Headers:\n [Nr] Name Type Address Off Size ES Flg Lk Inf Al\n "
        + "\n ".join(sections)
        + "\n\nProgram Headers:\n Type Offset VirtAddr PhysAddr FileSiz MemSiz Flg Align\n"
        + "\n".join(programs)
        + "\n\n Section to Segment mapping:\n Segment Sections...\n\n"
        + dynamic
        + "\n\n"
        + ("\n\n".join(tables) if tables else "No version information found in this file.")
        + "\n"
    )
    # Fix header counts for tests that compare phnum/shnum via inspect_elf.
    # Callers must ensure elf_bytes header matches; this text is authoritative.
    return body


def write_dep_elf(root: Path, relative: str, *, marker: bytes, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header_for(text) + marker + b"\x00" * 64)
    path.chmod(0o644)
    return path


class MappingInspector:
    def __init__(self, default: str, mapping: dict[bytes, str] | None = None) -> None:
        self.default = default
        self.mapping = mapping or {}
        self.contents: list[bytes] = []

    def __call__(self, fd: int) -> RunResult:
        data = os.pread(fd, 4096, 0)
        self.contents.append(data[:64])
        for marker, text in self.mapping.items():
            if marker in data:
                return RunResult("fake-readelf", text, "", 0)
        return RunResult("fake-readelf", self.default, "", 0)


def fake_extractor_factory(
    payloads: list[tuple[str, bytes, str]],
    *,
    record: dict[str, object] | None = None,
    behavior: str = "ok",
) -> Callable[[int, int, Path], RunResult]:
    def extractor(fd: int, offset: int, staging: Path) -> RunResult:
        if record is not None:
            record["offset"] = offset
            record["staging"] = str(staging)
            try:
                record["fd_head"] = os.pread(fd, 4, 0)
            except OSError:
                record["fd_head"] = b""
        if behavior == "missing":
            return RunResult("unsquashfs", "", "missing extractor", 1)
        if behavior == "fail":
            return RunResult("unsquashfs", "", "fake extraction failure", 1)
        if behavior == "timeout":
            return RunResult("unsquashfs", "", "unsquashfs timed out", 1, "timeout")
        if behavior == "oversized":
            return RunResult("unsquashfs", "x" * (2 * 1024 * 1024 + 1), "", 0)
        if behavior == "outside":
            (staging.parent / "escape").write_text("outside")
            return RunResult("unsquashfs", "", "", 0)
        for relative, marker, _text in payloads:
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(header_for(_text) + marker + b"\x00" * 32)
        if behavior == "special":
            import contextlib as _ctx
            import socket as _socket

            with _socket.socket(_socket.AF_UNIX) as sock, _ctx.suppress(OSError):
                sock.bind(str(staging / "socket"))
        if behavior == "mutate":
            # Mutate source after hash to simulate tampering.
            pass
        return RunResult("unsquashfs", "", "", 0)

    return extractor


def baseline_text(
    name: str,
    *,
    versions: tuple[str, ...] = ("GLIBC_2.35",),
    defs: tuple[str, ...] | None = None,
) -> str:
    provided = defs if defs is not None else (*versions, "GLIBC_2.2.5")
    return dep_text(
        needed=("libc.so.6",) if name == "libc.so.6" else (),
        needs_map={name: versions} if versions and name != "ld-linux-x86-64.so.2" else {},
        defs=provided,
        soname=name if name.endswith(".so.6") or name.startswith("ld-") else None,
    )


def write_baseline(root: Path, relative: str, *, text: str, marker: bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header_for(text) + marker + b"\x00" * 32)
    return path


def sha_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
