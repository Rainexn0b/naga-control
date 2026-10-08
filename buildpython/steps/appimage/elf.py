"""Static GNU readelf inspection; never execute or import the inspected payload."""

from __future__ import annotations

import os
import re
import selectors
import subprocess
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass

from ...utils.subproc import RunResult
from .versions import (
    VersionDef,
    VersionNeed,
    glibc_version,
    parse_tables,
    parse_tables_versions,
    table_field,
)

MAX_OUTPUT = 2 * 1024 * 1024
TIMEOUT = 10.0
READELF = "/usr/bin/readelf"
BASELINE_PRIVATE_ALLOW = ("libc.so.6", "ld-linux-x86-64.so.2")


@dataclass(frozen=True)
class ElfInfo:
    elf_class: str
    endianness: str
    machine: str
    elf_type: str
    interpreter: str | None
    version_needs: tuple[VersionNeed, ...]
    required_glibc: tuple[str, ...]
    other_needed_versions: tuple[str, ...]
    needed_libraries: tuple[str, ...]
    dependency_policy: str = "unvalidated inventory only; DT_NEEDED/provider closure not evaluated"
    soname: str | None = None
    rpath: tuple[str, ...] = ()
    runpath: tuple[str, ...] = ()
    version_defs: tuple[VersionDef, ...] = ()


Inspector = Callable[[int], RunResult]


@contextmanager
def _terminate_on_error(process: subprocess.Popen[bytes]) -> Generator[None, None, None]:
    try:
        yield
    except BaseException:
        process.kill()
        process.wait()
        raise


def readelf(fd: int) -> RunResult:
    """Inspect the open snapshot with a fixed host tool and a clean environment.

    Pipes are consumed incrementally so a hostile object cannot cause unbounded
    output buffering. The descriptor, not a mutable payload pathname, is passed.
    """
    args = [
        READELF,
        "--wide",
        "--file-header",
        "--program-headers",
        "--section-headers",
        "--dynamic",
        "--version-info",
        f"/proc/self/fd/{fd}",
    ]
    chunks: dict[str, list[bytes]] = {"stdout": [], "stderr": []}
    with subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        pass_fds=(fd,),
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        cwd="/",
    ) as process:
        assert process.stdout is not None and process.stderr is not None
        with _terminate_on_error(process), selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            deadline, size = time.monotonic() + TIMEOUT, 0
            failure = ""
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    failure = "readelf timed out"
                    break
                for key, _ in selector.select(remaining):
                    data = os.read(key.fd, 65536)
                    size += len(data)
                    if size > MAX_OUTPUT:
                        failure = "readelf output limit exceeded"
                        break
                    if data:
                        chunks[str(key.data)].append(data)
                    else:
                        selector.unregister(key.fileobj)
                if failure:
                    break
            if failure:
                process.kill()
                process.wait()
                return RunResult("host-readelf", "", failure, 1)
            try:
                code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                return RunResult("host-readelf", "", "readelf timed out", 1)
    try:
        stdout = b"".join(chunks["stdout"]).decode("utf-8", errors="strict")
        stderr = b"".join(chunks["stderr"]).decode("utf-8", errors="strict")
    except UnicodeError:
        raise ValueError("readelf returned non-UTF8 output") from None
    return RunResult("host-readelf", stdout, stderr, code)


def _tables(text: str) -> dict[str, tuple[int, int, list[str]]]:
    return parse_tables(text)


def _dynamic(
    text: str, tables: dict[str, tuple[int, int, list[str]]]
) -> tuple[tuple[str, ...], str | None, tuple[str, ...], tuple[str, ...]]:
    """Cross-check version-tag presence, not library/provider resolution policy."""
    blocks = re.findall(
        r"^Dynamic section at offset 0x[0-9a-f]+ contains (\d+) entries:\n[^\n]+\n(.*?)(?:\n\n|\Z)",
        text,
        re.M | re.S,
    )
    if not blocks:
        if (
            text.count("There is no dynamic section in this file.") != 1
            or tables
            or re.search(r"\bDYNAMIC\b", text)
        ):
            raise ValueError("missing dynamic/version metadata")
        return (), None, (), ()
    if len(blocks) != 1:
        raise ValueError("duplicate dynamic section")
    declared, body = blocks[0]
    rows = [line for line in body.splitlines() if line.strip()]
    tags: dict[str, list[str]] = {}
    for row in rows:
        match = re.fullmatch(r"\s*0x[0-9a-f]+\s+\(([^)]+)\)\s+(.+)", row)
        if match is None:
            raise ValueError("malformed dynamic entry")
        tags.setdefault(match[1], []).append(match[2].strip())
    if (
        len(rows) != int(declared)
        or not rows
        or len(tags.get("NULL", [])) != 1
        or re.fullmatch(r"\s*0x0+\s+\(NULL\)\s+0x0+", rows[-1]) is None
    ):
        raise ValueError("truncated dynamic section")
    for kind, tag in (("needs", "VERNEED"), ("definition", "VERDEF"), ("symbols", "VERSYM")):
        present = kind in tables
        if len(tags.get(tag, [])) != int(present):
            raise ValueError("inconsistent dynamic/version table presence")
        if present:
            section_type = {"needs": "VERNEED", "definition": "VERDEF", "symbols": "VERSYM"}[kind]
            addresses = re.findall(rf"\[\s*\d+\]\s+\S+\s+{section_type}\s+([0-9a-f]+)", text)
            if (
                len(addresses) != 1
                or re.fullmatch(r"0x[0-9a-f]+", tags[tag][0]) is None
                or int(tags[tag][0], 16) != int(addresses[0], 16)
            ):
                raise ValueError("inconsistent dynamic/version table address")
        if tag != "VERSYM" and tags.get(tag + "NUM", []) != (
            [str(tables[kind][0])] if present else []
        ):
            raise ValueError("inconsistent dynamic/version table count")
    libraries: list[str] = []
    for value in tags.get("NEEDED", []):
        match = re.fullmatch(r"Shared library: \[([^\]\n]+)\]", value)
        if match is None:
            raise ValueError("malformed DT_NEEDED inventory")
        libraries.append(match[1])
    soname: str | None = None
    for value in tags.get("SONAME", []):
        match = re.fullmatch(r"Library soname: \[([^\]\n]*)\]", value)
        if match is None or soname is not None or not match[1]:
            raise ValueError("malformed DT_SONAME inventory")
        if "/" in match[1] or any(ord(c) < 32 for c in match[1]):
            raise ValueError("malformed DT_SONAME inventory")
        soname = match[1]
    rpath: tuple[str, ...] = ()
    runpath: tuple[str, ...] = ()
    for tag, label in (("RPATH", "rpath"), ("RUNPATH", "runpath")):
        values = tags.get(tag, [])
        if len(values) > 1:
            raise ValueError(f"malformed DT_{tag} inventory")
        if values:
            match = re.fullmatch(rf"Library {label}: \[(.*)\]", values[0])
            if match is None:
                raise ValueError(f"malformed DT_{tag} inventory")
            parts = tuple(match[1].split(":"))
            if tag == "RPATH":
                rpath = parts
            else:
                runpath = parts
    return tuple(libraries), soname, rpath, runpath


def _build_info(
    text: str,
    needs: tuple[VersionNeed, ...],
    defs: tuple[VersionDef, ...],
    libraries: tuple[str, ...],
    soname: str | None,
    rpath: tuple[str, ...],
    runpath: tuple[str, ...],
) -> ElfInfo:
    names = {name for need in needs for name in need.names}
    glibc = {n for n in names if n.startswith("GLIBC") and not n.startswith("GLIBCXX_")}
    versions = tuple(sorted(glibc, key=glibc_version))
    found = re.findall(r"\[Requesting program interpreter: ([^\]\n]+)\]", text)
    return ElfInfo(
        table_field(text, "Class"),
        table_field(text, "Data"),
        table_field(text, "Machine"),
        table_field(text, "Type").split()[0],
        found[0] if found else None,
        needs,
        versions,
        tuple(sorted(names - glibc)),
        libraries,
        soname=soname,
        rpath=rpath,
        runpath=runpath,
        version_defs=defs,
    )


def parse_readelf(text: str) -> ElfInfo:
    """Parse complete --wide GNU output; definitions never become requirements."""
    if not text.startswith("ELF Header:\n") or len(text.encode()) > MAX_OUTPUT:
        raise ValueError("missing ELF header or oversized output")
    interpreters = re.findall(r"\[Requesting program interpreter: ([^\]\n]+)\]", text)
    interp_headers = re.findall(r"^\s*INTERP\s+0x", text, re.M)
    if len(interpreters) != len(interp_headers) or len(interpreters) > 1:
        raise ValueError("missing or ambiguous interpreter")
    tables = _tables(text)
    needs, defs = parse_tables_versions(tables)
    libraries, soname, rpath, runpath = _dynamic(text, tables)
    return _build_info(text, needs, defs, libraries, soname, rpath, runpath)


def parse_baseline_provider(text: str, *, provider_key: str) -> ElfInfo:
    """Parse trusted baseline glibc/loader with internal PRIVATE needs allowed."""
    if provider_key not in BASELINE_PRIVATE_ALLOW:
        raise ValueError("baseline PRIVATE allowance only for glibc/loader pair")
    if not text.startswith("ELF Header:\n") or len(text.encode()) > MAX_OUTPUT:
        raise ValueError("missing ELF header or oversized output")
    tables = _tables(text)
    needs, defs = parse_tables_versions(tables)
    libraries, soname, rpath, runpath = _dynamic(text, tables)
    names = {n for need in needs for n in need.names if n != "GLIBC_PRIVATE"}
    glibc = {n for n in names if n.startswith("GLIBC") and not n.startswith("GLIBCXX_")}
    versions = tuple(sorted(glibc, key=glibc_version))
    found = re.findall(r"\[Requesting program interpreter: ([^\]\n]+)\]", text)
    other = (
        {n for need in needs for n in need.names}
        - {n for n in names if n.startswith("GLIBC") and not n.startswith("GLIBCXX_")}
        - {"GLIBC_PRIVATE"}
    )
    # Keep PRIVATE in needs for export matching; exclude it from requirement floor.
    return ElfInfo(
        table_field(text, "Class"),
        table_field(text, "Data"),
        table_field(text, "Machine"),
        table_field(text, "Type").split()[0],
        found[0] if found else None,
        needs,
        versions,
        tuple(sorted(other - {n for n in versions})),
        libraries,
        soname=soname,
        rpath=rpath,
        runpath=runpath,
        version_defs=defs,
    )


def inspect_elf(fd: int, header: bytes, inspector: Inspector) -> ElfInfo:
    if (
        len(header) < 64
        or header[:7] != b"\x7fELF\x02\x01\x01"
        or int.from_bytes(header[20:24], "little") != 1
        or int.from_bytes(header[52:54], "little") != 64
        or int.from_bytes(header[54:56], "little") != 56
        or int.from_bytes(header[58:60], "little") != 64
    ):
        raise ValueError("unsupported or truncated ELF identification")
    result = inspector(fd)
    if result.exit_code or result.skip_reason or result.stderr:
        raise ValueError("readelf failed, skipped, or emitted diagnostics")
    info = parse_readelf(result.stdout)
    binary_type = int.from_bytes(header[16:18], "little")
    if (
        info.elf_class != "ELF64"
        or info.endianness != "2's complement, little endian"
        or info.machine != "Advanced Micro Devices X86-64"
        or int.from_bytes(header[18:20], "little") != 62
        or {2: "EXEC", 3: "DYN"}.get(binary_type) != info.elf_type
        or int.from_bytes(header[56:58], "little")
        != int(table_field(result.stdout, "Number of program headers"))
        or int.from_bytes(header[60:62], "little")
        != int(table_field(result.stdout, "Number of section headers"))
    ):
        raise ValueError("unsupported architecture/type or inconsistent ELF header")
    return info
