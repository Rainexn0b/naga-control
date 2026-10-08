"""GNU version-table parsing; strict, never executes the payload."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class VersionNeed:
    provider_name: str
    names: tuple[str, ...]


@dataclass(frozen=True)
class VersionDef:
    name: str


def glibc_version(name: str) -> tuple[int, ...]:
    match = re.fullmatch(r"GLIBC_([0-9]+(?:\.[0-9]+)+)", name)
    if match is None:
        raise ValueError(f"GLIBC_PRIVATE or unknown GLIBC requirement rejected: {name!a}")
    parts = tuple(int(part) for part in match[1].split("."))
    while len(parts) > 2 and parts[-1] == 0:
        parts = parts[:-1]
    return parts


def table_field(text: str, name: str) -> str:
    matches = re.findall(rf"^\s*{re.escape(name)}:\s*(.+)$", text, re.MULTILINE)
    if len(matches) != 1:
        raise ValueError("missing or duplicate ELF header field")
    return matches[0].strip()


def parse_tables(text: str) -> dict[str, tuple[int, int, list[str]]]:
    """Require complete section/program tables, including their declared counts."""
    counts = {n: table_field(text, f"Number of {n} headers") for n in ("section", "program")}
    if any(not v.isdecimal() or int(v) > 65535 for v in counts.values()):
        raise ValueError("unsupported ELF table count")
    sections = re.findall(r"^\s*\[\s*(\d+)\]\s+(.+)$", text, re.MULTILINE)
    if int(counts["section"]) == 0 or [int(i) for i, _ in sections] != list(
        range(int(counts["section"]))
    ):
        raise ValueError("missing or incomplete section headers")
    program = re.search(
        r"^Program Headers:\n(.*?)(?:\n\s*Section to Segment mapping:|\n\n|\Z)", text, re.S | re.M
    )
    if program is None:
        raise ValueError("missing program headers")
    rows = [
        line for line in program[1].splitlines()[1:] if line.strip() and "[Requesting" not in line
    ]
    if len(rows) != int(counts["program"]) or not rows:
        raise ValueError("incomplete program headers")
    for row in rows:
        if (
            re.fullmatch(
                r"\s*\S+\s+0x[0-9a-f]+\s+0x[0-9a-f]+\s+0x[0-9a-f]+\s+0x[0-9a-f]+\s+0x[0-9a-f]+\s+[ RWE]+\s+0x[0-9a-f]+\s*",
                row,
            )
            is None
        ):
            raise ValueError("malformed program header")
    if text.count("Section Headers:\n") != 1:
        raise ValueError("missing or duplicate section header table")
    result: dict[str, tuple[int, int, list[str]]] = {}
    for index, row in sections:
        fields = row.split()
        start = 1 if index == "0" else 2
        if (
            len(fields) not in (start + 7, start + 8)
            or not all(re.fullmatch(r"[0-9a-f]+", v) for v in fields[start : start + 4])
            or not all(v.isdecimal() for v in fields[-3:])
        ):
            raise ValueError("malformed section header")
        for section_type, kind in (
            ("VERSYM", "symbols"),
            ("VERDEF", "definition"),
            ("VERNEED", "needs"),
        ):
            if fields[start - 1] == section_type:
                if kind in result:
                    raise ValueError("duplicate version section")
                result[kind] = (0, int(fields[start + 2], 16), [])
    blocks = re.split(r"(?=^Version (?:symbols|definition|needs) section )", text, flags=re.M)[1:]
    seen: set[str] = set()
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        header = re.fullmatch(
            r"Version (symbols|definition|needs) section '[^']+' contains (\d+) entries:", lines[0]
        )
        if header is None or header[1] not in result or header[1] in seen:
            raise ValueError("malformed or unexpected version table")
        kind, count = header[1], int(header[2])
        if (
            count == 0
            or len(lines) < 3
            or re.fullmatch(
                r"Addr: 0x[0-9a-f]+\s+Offset: 0x[0-9a-f]+\s+Link: \d+ \([^)]+\)", lines[1]
            )
            is None
        ):
            raise ValueError("incomplete version table")
        if kind == "symbols" and result[kind][1] != count * 2:
            raise ValueError("inconsistent version symbol table size")
        result[kind] = (count, result[kind][1], lines[2:])
        seen.add(kind)
    if seen != set(result) or (
        not seen and text.count("No version information found in this file.") != 1
    ):
        raise ValueError("missing version information")
    return result


def parse_tables_versions(
    tables: dict[str, tuple[int, int, list[str]]],
) -> tuple[tuple[VersionNeed, ...], tuple[VersionDef, ...]]:
    """Parse VERNEED/VERDEF with count/truncation checks; defs never become needs."""
    needs: list[VersionNeed] = []
    defs: list[VersionDef] = []
    symbol_pattern = r"(?<!\S)[0-9a-f]+h?\s*\([^)]+\)(?!\S)"
    for kind, (count, size, lines) in tables.items():
        entries, remaining, expected_size, provider = 0, 0, 0, ""
        names: list[str] = []
        current_def: str = ""
        for line in lines:
            if kind == "symbols":
                match = re.fullmatch(r"[0-9a-f]+:\s+(.+)", line)
                if match is None:
                    raise ValueError("malformed version symbols")
                symbols = re.findall(symbol_pattern, match[1])
                if not symbols or re.sub(symbol_pattern, "", match[1]).strip():
                    raise ValueError("malformed version symbol entries")
                entries += len(symbols)
                expected_size += len(symbols) * 2
                continue
            primary = (
                r"(?:0x)?[0-9a-f]+: Version: 1\s+File: (\S+)\s+Cnt: (\d+)"
                if kind == "needs"
                else r"(?:0x)?[0-9a-f]+: Rev: 1\s+Flags: \S+\s+Index: \d+\s+Cnt: (\d+)\s+Name: (\S+)"
            )
            match = re.fullmatch(primary, line)
            if match:
                if remaining:
                    raise ValueError("truncated version auxiliary entries")
                entries += 1
                if kind == "needs":
                    if provider:
                        needs.append(VersionNeed(provider, tuple(names)))
                    provider, names, remaining = match[1], [], int(match[2])
                    expected_size += 16 + remaining * 16
                else:
                    current_def = match[2]
                    defs.append(VersionDef(current_def))
                    remaining = int(match[1]) - 1
                    expected_size += 20 + int(match[1]) * 8
                if remaining < (1 if kind == "needs" else 0):
                    raise ValueError("invalid version auxiliary count")
                continue
            auxiliary = (
                r"(?:0x)?[0-9a-f]+:\s+Name: (\S+)\s+Flags: \S+\s+Version: \d+"
                if kind == "needs"
                else r"(?:0x)?[0-9a-f]+:\s+Parent \d+: (\S+)"
            )
            match = re.fullmatch(auxiliary, line)
            if match is None or remaining <= 0:
                raise ValueError("malformed version auxiliary entry")
            remaining -= 1
            if kind == "needs":
                names.append(match[1])
            else:
                defs.append(VersionDef(match[1]))
        if remaining:
            raise ValueError("truncated version auxiliary entries")
        if entries != count:
            raise ValueError("incomplete version table entries")
        if size != expected_size:
            raise ValueError("inconsistent version section size")
        if kind == "needs" and provider:
            needs.append(VersionNeed(provider, tuple(names)))
    return tuple(needs), tuple(defs)
