"""Preliminary policy and JSON receipt tests; all inspectors are fakes."""

import hashlib
import json
import subprocess
from pathlib import Path
from typing import cast

import pytest
from appimage_abi_fakes import FakeInspector, output, write_elf

from buildpython.steps.appimage import abi
from buildpython.utils.subproc import RunResult


@pytest.mark.parametrize(
    "names,passed",
    [
        (("GLIBC_2.9",), True),
        (("GLIBC_2.35",), True),
        (("GLIBC_2.35.0",), True),
        (("GLIBC_2.36",), False),
        (("GLIBC_2.35.1",), False),
        (("GLIBC_2.44",), False),
        (("GLIBC_PRIVATE",), False),
        (("GLIBC_ABI_DT_RELR",), False),
    ],
)
def test_baseline_requirements(tmp_path: Path, names: tuple[str, ...], passed: bool) -> None:
    path = write_elf(tmp_path)
    fake = FakeInspector(output(needs=names))
    report = abi.audit(tmp_path, inspector=fake)
    assert (report.status == "pass") == passed
    assert len(report.payloads) == 1
    assert report.payloads[0].paths == ("usr/lib/payload",)
    assert report.payloads[0].sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    if not passed:
        assert "usr/lib/payload:" in " ".join(report.errors)
        assert names[0] in " ".join(report.errors)


def test_new_glibc_definition_does_not_raise_requirement_floor(tmp_path: Path) -> None:
    write_elf(tmp_path, definitions=True)
    report = abi.audit(tmp_path, inspector=FakeInspector(output(definitions=("GLIBC_2.44",))))
    assert report.status == "pass"
    assert report.payloads[0].elf is not None
    assert report.payloads[0].elf.required_glibc == ("GLIBC_2.35",)


def test_cxx_requirements_are_not_a_guessed_provider_or_cpu_pass(tmp_path: Path) -> None:
    write_elf(tmp_path)
    report = abi.audit(
        tmp_path, inspector=FakeInspector(output(needs=("GLIBCXX_99.1", "CXXABI_99.2")))
    )
    assert report.status == "pass"
    assert report.payloads[0].elf is not None
    assert report.payloads[0].elf.other_needed_versions == ("CXXABI_99.2", "GLIBCXX_99.1")
    assert report.scope == "staged-appdir/preliminary"
    assert report.baseline == "Ubuntu 22.04 / glibc 2.35 / x86_64"
    limitations = " ".join(report.unvalidated)
    assert "GLIBCXX/CXXABI/provider and runtime loads not accepted" in limitations
    assert "CPU ISA feature compatibility not evaluated" in limitations
    assert "DT_NEEDED/provider closure" in limitations


@pytest.mark.parametrize(
    "field,value",
    [
        ("elf_class", "ELF32"),
        ("endian", "2's complement, big endian"),
        ("machine", "AArch64"),
        ("elf_type", "REL"),
        ("elf_type", "CORE"),
    ],
)
def test_wrong_readelf_architecture_or_type_fails(tmp_path: Path, field: str, value: str) -> None:
    write_elf(tmp_path)
    report = abi.audit(tmp_path, inspector=FakeInspector(output(**{field: value})))
    assert report.status == "fail"
    assert "unsupported architecture/type" in " ".join(report.errors)


@pytest.mark.parametrize(
    "offset,value",
    [
        (4, 1),
        (5, 2),
        (6, 0),
        (16, 1),
        (18, 183),
        (20, 2),
        (52, 0),
        (54, 0),
        (56, 2),
        (58, 0),
        (60, 5),
    ],
)
def test_binary_header_disagreement_cannot_be_hidden_by_inspector(
    tmp_path: Path, offset: int, value: int
) -> None:
    path = write_elf(tmp_path)
    data = bytearray(path.read_bytes())
    data[offset] = value
    path.write_bytes(data)
    report = abi.audit(tmp_path, inspector=FakeInspector())
    assert report.status == "fail"


@pytest.mark.parametrize(
    "loader,passed",
    [
        ("/lib64/ld-linux-x86-64.so.2", True),
        ("/lib/ld-musl-x86_64.so.1", False),
        ("/artifact/loader", False),
    ],
)
def test_loader_policy(tmp_path: Path, loader: str, passed: bool) -> None:
    write_elf(tmp_path, interpreter=True)
    report = abi.audit(tmp_path, inspector=FakeInspector(output(interpreter=loader)))
    assert (report.status == "pass") == passed
    assert report.payloads[0].elf is not None
    assert report.payloads[0].elf.interpreter == loader


def test_exec_and_unversioned_payloads_are_supported(tmp_path: Path) -> None:
    path = write_elf(tmp_path, needs=False)
    data = bytearray(path.read_bytes())
    data[16:18] = (2).to_bytes(2, "little")
    path.write_bytes(data)
    report = abi.audit(tmp_path, inspector=FakeInspector(output(needs=(), elf_type="EXEC")))
    assert report.status == "pass"


@pytest.mark.parametrize(
    "result",
    [
        RunResult("fake", output(), "", 4),
        RunResult("fake", output(), "readelf warning", 0),
        RunResult("fake", output(), "", 0, "tool skipped"),
        RunResult("fake", "", "", 0),
        RunResult("fake", output()[:-30], "", 0),
    ],
)
def test_failed_skipped_empty_or_truncated_inspector_is_not_a_pass(
    tmp_path: Path, result: RunResult
) -> None:
    write_elf(tmp_path)
    report = abi.audit(tmp_path, inspector=lambda _fd: result)
    assert report.status == "fail"
    assert not report.inventory_complete
    assert report.payloads[0].elf is None


@pytest.mark.parametrize("failure", [FileNotFoundError, PermissionError, subprocess.TimeoutExpired])
def test_inspector_missing_unreadable_or_timed_out_is_sanitized(
    tmp_path: Path, failure: type[Exception]
) -> None:
    write_elf(tmp_path)

    def unavailable(_fd: int) -> RunResult:
        if failure is subprocess.TimeoutExpired:
            raise subprocess.TimeoutExpired("/private/path", 1)
        raise failure("/private/path")

    report = abi.audit(tmp_path, inspector=unavailable)
    assert report.status == "fail"
    assert "/private/path" not in " ".join(report.errors)
    assert failure.__name__ in " ".join(report.errors)


def test_mutation_during_inspection_is_unsafe_and_retains_no_mismatched_hash(
    tmp_path: Path,
) -> None:
    path = write_elf(tmp_path)
    fake = FakeInspector()

    def mutate(fd: int) -> RunResult:
        result = fake(fd)
        path.write_bytes(path.read_bytes() + b"changed")
        return result

    report = abi.audit(tmp_path, inspector=mutate)
    assert report.status == "fail"
    assert report.payloads == ()
    assert "mutated during hash/readelf" in " ".join(report.errors)
    assert "inventory mutated" in " ".join(report.errors)


def test_cli_json_is_partial_deterministic_stdout_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write_elf(tmp_path)
    fake = FakeInspector()
    monkeypatch.setattr(abi, "readelf", fake)
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    assert abi.main([str(tmp_path)]) == 0
    first = capsys.readouterr()
    data = cast(dict[str, object], json.loads(first.out))
    assert data["status"] == "pass" and data["scope"] == "staged-appdir/preliminary"
    assert "abi_validated" not in first.out and "not accepted" in first.out
    assert "/tmp/" not in first.out and first.err == ""
    assert abi.main([str(tmp_path)]) == 0
    assert capsys.readouterr().out == first.out
    assert sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*")) == before
    assert len(fake.contents) == 2


def test_cli_failure_status_and_explicit_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert abi.main([str(tmp_path)]) == 1
    assert '"status": "fail"' in capsys.readouterr().out
    with pytest.raises(SystemExit) as failure:
        abi.main([])
    assert failure.value.code == 2
