"""Tiny synthetic bytes and GNU readelf text; no native compiler or ELF execution."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from buildpython.utils.subproc import RunResult


def output(
    *,
    needs: Sequence[str] = ("GLIBC_2.35",),
    definitions: Sequence[str] = (),
    interpreter: str | None = None,
    elf_class: str = "ELF64",
    endian: str = "2's complement, little endian",
    machine: str = "Advanced Micro Devices X86-64",
    elf_type: str = "DYN",
) -> str:
    sections = ["[ 0] NULL 0000000000000000 000000 000000 00 0 0 0"]
    tables: list[str] = []
    if needs or definitions:
        symbols = ["(*local*)", *(f"({name})" for name in (*needs, *definitions))]
        symbol_rows = [
            f" {start:03x}: "
            + " ".join(
                f"{i:x} {name}" for i, name in enumerate(symbols[start : start + 4], start=start)
            )
            for start in range(0, len(symbols), 4)
        ]
        sections.append(
            f"[ 1] .gnu.version VERSYM 0000000000000000 000000 {len(symbols) * 2:06x} 02 A 0 0 2"
        )
        tables.append(
            f"Version symbols section '.gnu.version' contains {len(symbols)} entries:\n"
            " Addr: 0x0000000000000000 Offset: 0x000000 Link: 0 (.dynsym)\n"
            + "\n".join(symbol_rows)
        )
    if definitions:
        sections.append(
            f"[ {len(sections)}] .gnu.version_d VERDEF 0000000000000000 000000 "
            f"{28 * len(definitions):06x} 00 A 0 0 8"
        )
        tables.append(
            f"Version definition section '.gnu.version_d' contains {len(definitions)} entries:\n"
            " Addr: 0x0000000000000000 Offset: 0x000000 Link: 0 (.dynstr)\n"
            + "\n".join(
                f" {i * 28:06x}: Rev: 1 Flags: none Index: {i + 1} Cnt: 1 Name: {name}"
                for i, name in enumerate(definitions)
            )
        )
    if needs:
        sections.append(
            f"[ {len(sections)}] .gnu.version_r VERNEED 0000000000000000 000000 "
            f"{16 * (1 + len(needs)):06x} 00 A 0 0 8"
        )
        tables.append(
            "Version needs section '.gnu.version_r' contains 1 entries:\n"
            " Addr: 0x0000000000000000 Offset: 0x000000 Link: 0 (.dynstr)\n"
            f" 000000: Version: 1 File: libc.so.6 Cnt: {len(needs)}\n"
            + "\n".join(
                f" {16 * (i + 1):06x}: Name: {name} Flags: none Version: {i + 2}"
                for i, name in enumerate(needs)
            )
        )
    dynamic = "There is no dynamic section in this file."
    if needs or definitions:
        tags = ["0x0000000000000001 (NEEDED) Shared library: [libc.so.6]"]
        if needs:
            tags += ["0x000000006ffffffe (VERNEED) 0x0", "0x000000006fffffff (VERNEEDNUM) 1"]
        if definitions:
            tags += [
                "0x000000006ffffffc (VERDEF) 0x0",
                f"0x000000006ffffffd (VERDEFNUM) {len(definitions)}",
            ]
        tags += ["0x000000006ffffff0 (VERSYM) 0x0", "0x0000000000000000 (NULL) 0x0"]
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
    return (
        "ELF Header:\n"
        f" Class: {elf_class}\n Data: {endian}\n Type: {elf_type} (Shared object file)\n"
        f" Machine: {machine}\n Number of program headers: {2 if interpreter else 1}\n"
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


def elf_bytes(*, needs: bool = True, definitions: bool = False, interpreter: bool = False) -> bytes:
    header = bytearray(64)
    header[:7] = b"\x7fELF\x02\x01\x01"
    header[16:18] = (3).to_bytes(2, "little")
    header[18:20] = (62).to_bytes(2, "little")
    header[20:24] = (1).to_bytes(4, "little")
    header[52:54] = (64).to_bytes(2, "little")
    header[54:56] = (56).to_bytes(2, "little")
    header[56:58] = (2 if interpreter else 1).to_bytes(2, "little")
    header[58:60] = (64).to_bytes(2, "little")
    header[60:62] = (1 + 2 * bool(needs or definitions) + needs + definitions).to_bytes(2, "little")
    return bytes(header) + b"synthetic payload, deliberately not an executable fixture"


def write_elf(root: Path, relative: str = "usr/lib/payload", **kwargs: bool) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(elf_bytes(**kwargs))
    return path


class FakeInspector:
    def __init__(self, text: str | None = None, *, code: int = 0, stderr: str = "") -> None:
        self.text = output() if text is None else text
        self.code = code
        self.stderr = stderr
        self.contents: list[bytes] = []

    def __call__(self, fd: int) -> RunResult:
        self.contents.append(os.pread(fd, 4096, 0))
        return RunResult("fake-readelf", self.text, self.stderr, self.code)
