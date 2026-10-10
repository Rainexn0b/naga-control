"""Parser and host-inspector boundaries, using synthetic output and fake processes."""

import os
import subprocess
from pathlib import Path
from typing import BinaryIO, cast

import pytest
from appimage_abi_fakes import output, write_elf

from buildpython.steps.appimage import elf


def test_needs_only_not_definitions_or_symbol_display() -> None:
    info = elf.parse_readelf(output(needs=("GLIBC_2.9", "GLIBC_2.35"), definitions=("GLIBC_2.44",)))
    assert info.required_glibc == ("GLIBC_2.9", "GLIBC_2.35")
    assert info.version_needs[0].provider_name == "libc.so.6"
    assert info.other_needed_versions == ()


def test_numeric_glibc_order_and_trailing_zero_components() -> None:
    assert elf.glibc_version("GLIBC_2.9") < elf.glibc_version("GLIBC_2.35")
    assert elf.glibc_version("GLIBC_2.35.0") == (2, 35)
    assert elf.glibc_version("GLIBC_2.35.1") > (2, 35)


@pytest.mark.parametrize(
    "name", ["GLIBC_PRIVATE", "GLIBC_ABI_DT_RELR", "GLIBC_2", "GLIBC_2.x", "GLIBC_FUTURE"]
)
def test_unknown_glibc_requirements_fail_closed(name: str) -> None:
    with pytest.raises(ValueError, match="GLIBC_PRIVATE or unknown"):
        elf.parse_readelf(output(needs=(name,)))


def test_cxx_and_other_versions_are_unvalidated_inventory() -> None:
    info = elf.parse_readelf(output(needs=("GLIBC_2.35", "GLIBCXX_99.0", "CXXABI_9.0", "OTHER_1")))
    assert info.required_glibc == ("GLIBC_2.35",)
    assert info.other_needed_versions == ("CXXABI_9.0", "GLIBCXX_99.0", "OTHER_1")
    assert info.needed_libraries == ("libc.so.6",)
    assert "unvalidated inventory only" in info.dependency_policy


@pytest.mark.parametrize(
    "old,new",
    [
        ("contains 5 entries:", "contains 4 entries:"),
        ("(VERNEEDNUM) 1", "(VERNEEDNUM) 2"),
        ("(VERNEED) 0x0", "(VERNEED) 0x40"),
        ("(VERNEED) 0x0", "(IGNORED) 0x0"),
        ("(NULL) 0x0", "(FLAGS) 0x0"),
        ("Shared library: [libc.so.6]", "Shared library: malformed"),
        (".gnu.version_r VERNEED", ".gnu.version_r PROGBITS"),
    ],
)
def test_dynamic_version_metadata_cannot_hide_missing_or_malformed_needs(
    old: str, new: str
) -> None:
    text = output()
    assert old in text
    with pytest.raises(ValueError):
        elf.parse_readelf(text.replace(old, new))


def test_hidden_symbol_and_multiple_need_provider_records() -> None:
    text = output(needs=("GLIBC_2.9", "GLIBC_2.35"))
    text = text.replace("1 (GLIBC_2.9)", "1h(GLIBC_2.9)")
    assert elf.parse_readelf(text).required_glibc == ("GLIBC_2.9", "GLIBC_2.35")
    text = text.replace("(VERNEEDNUM) 1", "(VERNEEDNUM) 2")
    text = text.replace("000030 00 A", "000040 00 A")
    text = text.replace("contains 1 entries:", "contains 2 entries:")
    text = text.replace("File: libc.so.6 Cnt: 2", "File: libc.so.6 Cnt: 1")
    text = text.replace(
        " 000020: Name:", " 000020: Version: 1 File: libsecond.so Cnt: 1\n 000030: Name:"
    )
    info = elf.parse_readelf(text)
    assert [need.provider_name for need in info.version_needs] == ["libc.so.6", "libsecond.so"]


@pytest.mark.parametrize("index", ["a", "f", "10", "1f"])
@pytest.mark.parametrize("hidden", [False, True])
def test_hex_symbol_indices_and_hidden_hex_do_not_become_requirements(
    index: str, hidden: bool
) -> None:
    names = ("GLIBC_2.35", *(f"OTHER_{i}" for i in range(2, 32)))
    text = output(needs=names, definitions=("GLIBC_2.44",))
    name = names[int(index, 16) - 1]
    token = f"{index} ({name})"
    assert token in text and " 010:" in text
    if hidden:
        text = text.replace(token, f"{index}h({name})")
    info = elf.parse_readelf(text)
    assert info.required_glibc == ("GLIBC_2.35",)
    assert info.version_needs[0].names == names
    assert info.other_needed_versions == tuple(sorted(names[1:]))


@pytest.mark.parametrize("index", ["g", "ag", "0xa", "ahh", "+a", "", "a?"])
def test_malformed_hex_symbol_tokens_fail_closed(index: str) -> None:
    names = tuple(f"OTHER_{i}" for i in range(1, 11))
    text = output(needs=names)
    assert "a (OTHER_10)" in text
    with pytest.raises(ValueError, match="malformed version symbol entries"):
        elf.parse_readelf(text.replace("a (OTHER_10)", f"{index} (OTHER_10)"))


def test_adjacent_hex_symbol_tokens_are_not_valid_separated_entries() -> None:
    text = output(needs=tuple(f"OTHER_{i}" for i in range(1, 11)))
    with pytest.raises(ValueError, match="malformed version symbol entries"):
        elf.parse_readelf(text.replace("9 (OTHER_9) a (OTHER_10)", "9 (OTHER_9)a (OTHER_10)"))


@pytest.mark.parametrize("alteration", ["missing", "extra", "declared_count", "section_size"])
def test_hex_symbols_keep_truncation_count_and_size_checks(alteration: str) -> None:
    text = output(needs=tuple(f"OTHER_{i}" for i in range(1, 11)))
    token = "a (OTHER_10)"
    if alteration == "missing":
        text = text.replace(token, "")
    elif alteration == "extra":
        text = text.replace(token, f"{token} {token}")
    elif alteration == "declared_count":
        text = text.replace("contains 11 entries:", "contains 10 entries:")
    else:
        text = text.replace("000016 02 A", "000014 02 A")
    with pytest.raises(
        ValueError, match=r"incomplete version table entries|version symbol table size"
    ):
        elf.parse_readelf(text)


def test_no_versions_and_definitions_only_are_legitimate() -> None:
    assert elf.parse_readelf(output(needs=())).required_glibc == ()
    assert (
        elf.parse_readelf(
            output(needs=(), definitions=("GLIBC_PRIVATE", "GLIBC_2.44"))
        ).required_glibc
        == ()
    )


@pytest.mark.parametrize(
    "old,new",
    [
        ("ELF Header:", "header missing"),
        (" Class: ELF64\n", ""),
        (" Machine: Advanced Micro Devices X86-64\n", ""),
        ("Number of section headers: 4", "Number of section headers: 999999999"),
        ("Number of section headers: 4", "Number of section headers: 0"),
        ("[ 2] .gnu.version_r", "[ 4] .gnu.version_r"),
        ("000020 00 A", "garbled 00 A"),
        (" LOAD 0x000000", " LOAD bad"),
        ("Program Headers:", ""),
        ("Version needs section", "Malformed needs section"),
        ("contains 1 entries:", "contains 2 entries:"),
        ("File: libc.so.6 Cnt: 1", "File: libc.so.6 Cnt: 2"),
        ("Name: GLIBC_2.35 Flags:", "Name: Flags:"),
        (" 000010: Name: GLIBC_2.35 Flags: none Version: 2\n", ""),
        (" 000: 0 (*local*) 1 (GLIBC_2.35)", " 000: truncated"),
        ("Addr: 0x0000000000000000 Offset:", "Addr: unknown Offset:"),
    ],
)
def test_malformed_and_truncated_output_never_passes(old: str, new: str) -> None:
    original = output()
    assert old in original
    with pytest.raises(ValueError):
        elf.parse_readelf(original.replace(old, new))


def test_version_definition_auxiliary_integrity_and_unknown_table() -> None:
    text = output(definitions=("GLIBC_2.44",))
    with pytest.raises(ValueError, match="auxiliary"):
        elf.parse_readelf(text.replace("Cnt: 1 Name: GLIBC_2.44", "Cnt: 2 Name: GLIBC_2.44"))
    with pytest.raises(ValueError):
        elf.parse_readelf(text + "\nVersion needs section '.extra' contains 1 entries:\n")
    with pytest.raises(ValueError):
        elf.parse_readelf(
            output(needs=()).replace("No version information found in this file.", "")
        )


def test_real_gnu_singular_entry_count_one_passes() -> None:
    text = output()
    assert "contains 1 entries:" in text
    singular = text.replace("contains 1 entries:", "contains 1 entry:")
    assert elf.parse_readelf(singular).required_glibc == ("GLIBC_2.35",)
    both = output(needs=("GLIBC_2.35",), definitions=("GLIBC_2.44",))
    singular_both = both.replace("contains 1 entries:", "contains 1 entry:")
    assert singular_both.count("contains 1 entry:") == 2
    assert elf.parse_readelf(singular_both).required_glibc == ("GLIBC_2.35",)


@pytest.mark.parametrize("count", [0, 2, 10])
def test_singular_entry_with_count_not_one_fails(count: int) -> None:
    text = output()
    bad = text.replace("contains 1 entries:", f"contains {count} entry:", 1)
    assert f"contains {count} entry:" in bad
    with pytest.raises(ValueError, match="malformed or unexpected version table"):
        elf.parse_readelf(bad)
    symbols = text.replace("contains 2 entries:", "contains 2 entry:", 1)
    with pytest.raises(ValueError, match="malformed or unexpected version table"):
        elf.parse_readelf(symbols)


def test_singular_truncated_aux_address_and_count_still_fail() -> None:
    singular = output().replace("contains 1 entries:", "contains 1 entry:")
    with pytest.raises(ValueError):
        elf.parse_readelf(
            singular.replace(" 000010: Name: GLIBC_2.35 Flags: none Version: 2\n", "")
        )
    with pytest.raises(ValueError):
        elf.parse_readelf(singular.replace("Addr: 0x0000000000000000 Offset:", "Addr: ? Offset:"))
    with pytest.raises(ValueError):
        elf.parse_readelf(singular.replace("contains 1 entry:", "contains 2 entry:", 1))


def test_interpreter_header_requires_exactly_one_complete_description() -> None:
    text = output(interpreter="/lib64/ld-linux-x86-64.so.2")
    assert elf.parse_readelf(text).interpreter == "/lib64/ld-linux-x86-64.so.2"
    with pytest.raises(ValueError, match="interpreter"):
        elf.parse_readelf(text.replace("[Requesting program interpreter:", "[malformed:"))


class _Process:
    def __init__(self, stdout: bytes, stderr: bytes = b"") -> None:
        self.killed = False
        self.stdout = self._pipe(stdout)
        self.stderr = self._pipe(stderr)

    @staticmethod
    def _pipe(data: bytes) -> BinaryIO:
        reader, writer = os.pipe()
        os.write(writer, data)
        os.close(writer)
        return cast(BinaryIO, os.fdopen(reader, "rb"))

    def __enter__(self) -> "_Process":
        return self

    def __exit__(self, *_args: object) -> None:
        self.stdout.close()
        self.stderr.close()

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        self.killed = True


def test_host_tool_argv_environment_descriptor_and_non_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_elf(tmp_path)
    process = _Process(b"synthetic tool stdout", b"synthetic stderr")
    monkeypatch.setenv("LD_PRELOAD", "/untrusted/lib.so")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/artifact/lib")
    monkeypatch.setenv("PATH", "/artifact/bin")

    def launch(args: list[str], **kwargs: object) -> _Process:
        assert args[:-1] == [
            "/usr/bin/readelf",
            "--wide",
            "--file-header",
            "--program-headers",
            "--section-headers",
            "--dynamic",
            "--version-info",
        ]
        fd = int(args[-1].rsplit("/", 1)[1])
        assert os.pread(fd, 4, 0) == b"\x7fELF"
        assert kwargs == {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "stdin": subprocess.DEVNULL,
            "pass_fds": (fd,),
            "env": {"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            "cwd": "/",
        }
        return process

    monkeypatch.setattr(elf.subprocess, "Popen", launch)
    with path.open("rb") as source:
        result = elf.readelf(source.fileno())
    assert result.stdout == "synthetic tool stdout"
    assert result.stderr == "synthetic stderr"
    assert result.exit_code == 0
    assert not process.killed


@pytest.mark.parametrize("timeout", [False, True])
def test_host_output_and_time_limits_kill_fake_process(
    monkeypatch: pytest.MonkeyPatch, timeout: bool
) -> None:
    process = _Process(b"too much fake output")

    def launch(*_args: object, **_kwargs: object) -> _Process:
        return process

    monkeypatch.setattr(elf.subprocess, "Popen", launch)
    monkeypatch.setattr(elf, "TIMEOUT", -1.0 if timeout else 10.0)
    monkeypatch.setattr(elf, "MAX_OUTPUT", 4)
    result = elf.readelf(123)
    assert result.exit_code != 0 and process.killed
    assert "timed out" in result.stderr if timeout else "output limit" in result.stderr


def test_non_utf8_host_output_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    process = _Process(b"\xff")

    def launch(*_args: object, **_kwargs: object) -> _Process:
        return process

    monkeypatch.setattr(elf.subprocess, "Popen", launch)
    with pytest.raises(ValueError, match="non-UTF8"):
        elf.readelf(123)


def test_pipe_read_error_terminates_fake_inspector(monkeypatch: pytest.MonkeyPatch) -> None:
    process = _Process(b"synthetic output")

    def launch(*_args: object, **_kwargs: object) -> _Process:
        return process

    def unavailable(_fd: int, _size: int) -> bytes:
        raise OSError("synthetic pipe failure")

    monkeypatch.setattr(elf.subprocess, "Popen", launch)
    monkeypatch.setattr(elf.os, "read", unavailable)
    with pytest.raises(OSError):
        elf.readelf(123)
    assert process.killed
