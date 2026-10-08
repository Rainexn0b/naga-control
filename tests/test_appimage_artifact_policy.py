"""Policy: archives gap, PRIVATE, CLI scope; fakes only, no host execution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from appimage_artifact_fakes import (
    MappingInspector,
    baseline_text,
    dep_text,
    fake_extractor_factory,
    write_appimage_with_text,
    write_baseline,
)

from buildpython.steps.appimage import artifact
from buildpython.utils.subproc import RunResult


def _base(tmp_path: Path, mapping: dict[bytes, str]) -> Path:
    root = tmp_path / "baseline"
    libc = baseline_text("libc.so.6", versions=("GLIBC_2.35",), defs=("GLIBC_2.35",))
    loader = dep_text(
        needed=(), needs_map={}, defs=("GLIBC_PRIVATE",), soname="ld-linux-x86-64.so.2"
    )
    mapping[b"p-libc"] = libc
    mapping[b"p-loader"] = loader
    write_baseline(root, "lib/x86_64-linux-gnu/libc.so.6", text=libc, marker=b"p-libc")
    write_baseline(root, "lib64/ld-linux-x86-64.so.2", text=loader, marker=b"p-loader")
    return root


def _outer() -> str:
    return dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})


def test_archive_gap_is_fail_not_pass(tmp_path: Path) -> None:
    mapping: dict[bytes, str] = {}
    baseline = _base(tmp_path, mapping)
    outer = _outer()
    inner = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    mapping[b"arc-pay"] = inner
    inspector = MappingInspector(outer, mapping)

    def with_archive(fd: int, offset: int, staging: Path) -> RunResult:
        from appimage_artifact_fakes import header_for

        target = staging / "usr/lib/a.so"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(header_for(inner) + b"arc-pay" + b"\x00" * 16)
        (staging / "libnumpy.a").write_bytes(b"!<arch>\nmember")
        return RunResult("unsquashfs", "", "", 0)

    art = tmp_path / "arc.AppImage"
    write_appimage_with_text(art, outer)
    report = artifact.audit_artifact(art, baseline, inspector=inspector, extractor=with_archive)
    assert report.status == "fail"
    assert "ar archive unsupported" in " ".join(report.errors)


def test_payload_private_fails_closed(tmp_path: Path) -> None:
    mapping: dict[bytes, str] = {}
    baseline = _base(tmp_path, mapping)
    outer = _outer()
    inner = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_PRIVATE",)})
    mapping[b"priv-pay"] = inner
    inspector = MappingInspector(outer, mapping)
    extractor = fake_extractor_factory([("usr/lib/a.so", b"priv-pay", inner)])
    art = tmp_path / "priv.AppImage"
    write_appimage_with_text(art, outer)
    report = artifact.audit_artifact(art, baseline, inspector=inspector, extractor=extractor)
    assert report.status == "fail"
    assert "PRIVATE" in " ".join(report.errors)


def test_cli_scope_and_no_false_claims(tmp_path: Path) -> None:
    mapping: dict[bytes, str] = {}
    baseline = _base(tmp_path, mapping)
    outer = _outer()
    inner = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    mapping[b"cli-pay"] = inner
    inspector = MappingInspector(outer, mapping)
    extractor = fake_extractor_factory([("usr/lib/a.so", b"cli-pay", inner)])
    art = tmp_path / "cli.AppImage"
    write_appimage_with_text(art, outer)
    report = artifact.audit_artifact(art, baseline, inspector=inspector, extractor=extractor)
    assert report.scope == "finished-appimage/static-runtime-abi"
    assert report.baseline == "Ubuntu 22.04 / glibc 2.35 / x86_64"
    text = " ".join([report.scope, report.baseline, " ".join(report.unvalidated)])
    assert "Ubuntu 22.04" in text and "glibc 2.35" in text
    assert "CPU ISA" in " ".join(report.unvalidated)
    assert "desktop" in " ".join(report.unvalidated).lower()
    assert "provenance" in " ".join(report.unvalidated).lower()
    for payload in report.payloads:
        paths = cast(list[str], payload["paths"])
        for path in paths:
            assert not path.startswith("/") and "/tmp/" not in path


def test_cli_missing_args_and_baseline(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        artifact.main([])
    assert exc.value.code == 2
    art = tmp_path / "missing.AppImage"
    art.write_bytes(b"fake")
    code = artifact.main([str(art), "--baseline-root", str(tmp_path / "nope")])
    assert code == 1
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["status"] == "fail" and data["scope"] == "finished-appimage/static-runtime-abi"
    assert str(tmp_path) not in out


def test_zero_elf_and_incomplete_fail(tmp_path: Path) -> None:
    mapping: dict[bytes, str] = {}
    baseline = _base(tmp_path, mapping)
    outer = _outer()
    inspector = MappingInspector(outer, mapping)
    extractor = fake_extractor_factory([])
    art = tmp_path / "empty.AppImage"
    write_appimage_with_text(art, outer)
    report = artifact.audit_artifact(art, baseline, inspector=inspector, extractor=extractor)
    assert report.status == "fail"
    assert "no successfully inspected elf" in " ".join(report.errors).lower()


def test_stdout_compact_json_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    mapping: dict[bytes, str] = {}
    baseline = _base(tmp_path, mapping)
    outer = _outer()
    art = tmp_path / "json.AppImage"
    write_appimage_with_text(art, outer)

    def fake_audit(first: Path, second: Path) -> artifact.GateReport:
        _ = (mapping, outer)
        return artifact.GateReport(
            "pass",
            artifact.SCOPE,
            artifact.BASELINE,
            {"name": first.name, "sha256": "abc", "size": 1},
            1,
            (),
            True,
            (),
        )

    monkeypatch.setattr(artifact, "audit_artifact", fake_audit)
    code = artifact.main([str(art), "--baseline-root", str(baseline)])
    assert code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert set(data) >= {"status", "scope", "baseline", "artifact", "errors"}
    assert data["scope"] == "finished-appimage/static-runtime-abi"
