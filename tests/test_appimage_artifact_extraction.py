"""Extractor seam: trusted flags, failures, confinement; fakes only."""

from __future__ import annotations

import os
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
    mapping[b"bl-libc"] = libc
    mapping[b"bl-loader"] = loader
    write_baseline(root, "lib/x86_64-linux-gnu/libc.so.6", text=libc, marker=b"bl-libc")
    write_baseline(root, "lib64/ld-linux-x86-64.so.2", text=loader, marker=b"bl-loader")
    return root


def _outer() -> str:
    return dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})


def _inner() -> tuple[bytes, str]:
    text = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    return b"pay-marker", text


def test_missing_extractor_fails(tmp_path: Path) -> None:
    mapping: dict[bytes, str] = {}
    baseline = _base(tmp_path, mapping)
    outer = _outer()
    inspector = MappingInspector(outer, mapping)
    marker, text = _inner()
    mapping[marker] = text
    extractor = fake_extractor_factory([("usr/lib/a.so", marker, text)], behavior="missing")
    art = tmp_path / "a.AppImage"
    write_appimage_with_text(art, outer)
    report = artifact.audit_artifact(art, baseline, inspector=inspector, extractor=extractor)
    assert report.status == "fail" and "extraction failed" in " ".join(report.errors)


def test_failing_extractor_fails(tmp_path: Path) -> None:
    mapping: dict[bytes, str] = {}
    baseline = _base(tmp_path, mapping)
    outer = _outer()
    inspector = MappingInspector(outer, mapping)
    marker, text = _inner()
    mapping[marker] = text
    extractor = fake_extractor_factory([("usr/lib/a.so", marker, text)], behavior="fail")
    art = tmp_path / "b.AppImage"
    write_appimage_with_text(art, outer)
    report = artifact.audit_artifact(art, baseline, inspector=inspector, extractor=extractor)
    assert report.status == "fail"


def test_timeout_and_oversized_fail(tmp_path: Path) -> None:
    for behavior in ("timeout", "oversized"):
        mapping: dict[bytes, str] = {}
        baseline = _base(tmp_path, mapping)
        outer = _outer()
        inspector = MappingInspector(outer, mapping)
        marker, text = _inner()
        mapping[marker] = text
        extractor = fake_extractor_factory([("usr/lib/a.so", marker, text)], behavior=behavior)
        art = tmp_path / f"{behavior}.AppImage"
        write_appimage_with_text(art, outer)
        report = artifact.audit_artifact(art, baseline, inspector=inspector, extractor=extractor)
        assert report.status == "fail", behavior


def test_outside_write_fails_and_cleanup(tmp_path: Path) -> None:
    mapping: dict[bytes, str] = {}
    baseline = _base(tmp_path, mapping)
    outer = _outer()
    inspector = MappingInspector(outer, mapping)
    marker, text = _inner()
    mapping[marker] = text
    extractor = fake_extractor_factory([("usr/lib/a.so", marker, text)], behavior="outside")
    art = tmp_path / "outside.AppImage"
    write_appimage_with_text(art, outer)
    report = artifact.audit_artifact(art, baseline, inspector=inspector, extractor=extractor)
    assert report.status == "fail" and "outside staging" in " ".join(report.errors)


def test_special_file_fails(tmp_path: Path) -> None:
    mapping: dict[bytes, str] = {}
    baseline = _base(tmp_path, mapping)
    outer = _outer()
    inspector = MappingInspector(outer, mapping)
    marker, text = _inner()
    mapping[marker] = text
    extractor = fake_extractor_factory([("usr/lib/a.so", marker, text)], behavior="special")
    art = tmp_path / "special.AppImage"
    write_appimage_with_text(art, outer)
    report = artifact.audit_artifact(art, baseline, inspector=inspector, extractor=extractor)
    assert report.status == "fail" and "nonregular" in " ".join(report.errors).lower()


def test_escape_symlink_fails(tmp_path: Path) -> None:
    mapping: dict[bytes, str] = {}
    baseline = _base(tmp_path, mapping)
    outer = _outer()
    marker, text = _inner()
    mapping[marker] = text
    inspector = MappingInspector(outer, mapping)

    def evil(fd: int, offset: int, staging: Path) -> RunResult:
        target = staging / "usr/lib/a.so"
        target.parent.mkdir(parents=True, exist_ok=True)
        from appimage_artifact_fakes import header_for

        target.write_bytes(header_for(text) + marker + b"\x00" * 16)
        (staging / "evil").symlink_to("/outside")
        return RunResult("unsquashfs", "", "", 0)

    art = tmp_path / "evil.AppImage"
    write_appimage_with_text(art, outer)
    report = artifact.audit_artifact(art, baseline, inspector=inspector, extractor=evil)
    assert report.status == "fail" and "escapes" in " ".join(report.errors).lower()


def test_mutation_fails(tmp_path: Path) -> None:
    mapping: dict[bytes, str] = {}
    baseline = _base(tmp_path, mapping)
    outer = _outer()
    marker, text = _inner()
    mapping[marker] = text
    inspector = MappingInspector(outer, mapping)
    art = tmp_path / "mut.AppImage"
    write_appimage_with_text(art, outer)

    def mutating(fd: int, offset: int, staging: Path) -> RunResult:
        target = staging / "usr/lib/a.so"
        target.parent.mkdir(parents=True, exist_ok=True)
        from appimage_artifact_fakes import header_for

        target.write_bytes(header_for(text) + marker + b"\x00" * 16)
        with art.open("ab") as handle:
            handle.write(b"tamper")
        return RunResult("unsquashfs", "", "", 0)

    report = artifact.audit_artifact(art, baseline, inspector=inspector, extractor=mutating)
    assert report.status == "fail" and "mutated" in " ".join(report.errors).lower()


def test_symlink_and_nonregular_source_fail(tmp_path: Path) -> None:
    mapping: dict[bytes, str] = {}
    baseline = _base(tmp_path, mapping)
    outer = _outer()
    inspector = MappingInspector(outer, mapping)
    extractor = fake_extractor_factory([])
    real = tmp_path / "real.AppImage"
    write_appimage_with_text(real, outer)
    link = tmp_path / "link.AppImage"
    link.symlink_to(real)
    assert (
        artifact.audit_artifact(link, baseline, inspector=inspector, extractor=extractor).status
        == "fail"
    )
    directory = tmp_path / "dir"
    directory.mkdir()
    assert (
        artifact.audit_artifact(
            directory, baseline, inspector=inspector, extractor=extractor
        ).status
        == "fail"
    )


def test_root_refused_before_extraction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mapping: dict[bytes, str] = {}
    baseline = _base(tmp_path, mapping)
    outer = _outer()
    inspector = MappingInspector(outer, mapping)
    called: list[int] = []

    def never(fd: int, offset: int, staging: Path) -> RunResult:
        called.append(1)
        return RunResult("unsquashfs", "", "", 0)

    art = tmp_path / "root.AppImage"
    write_appimage_with_text(art, outer)
    monkeypatch.setattr(artifact.os, "geteuid", lambda: 0)
    report = artifact.audit_artifact(art, baseline, inspector=inspector, extractor=never)
    assert report.status == "fail" and not called and "root" in " ".join(report.errors).lower()


def test_trusted_argv_env_and_fd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class Done(Exception):
        pass

    def fake_popen(args: list[str], **kwargs: object) -> RunResult:
        captured["args"] = args
        captured["kwargs"] = kwargs
        raise Done

    from buildpython.steps.appimage import extraction as _extraction

    monkeypatch.setattr(_extraction.subprocess, "Popen", fake_popen)
    staging = tmp_path / "stage"
    staging.mkdir()
    (tmp_path / "src").write_bytes(b"src")
    fd = os.open(tmp_path / "src", os.O_RDONLY)
    try:
        with pytest.raises(Done):
            _extraction.run_trusted_extractor(fd, 4096, staging / "root")
    finally:
        os.close(fd)
    args = cast(list[str], captured["args"])
    assert args[0] == "/usr/bin/unsquashfs"
    assert args[1:6] == ["-o", "4096", "-d", str(staging / "root"), "-no-progress"]
    assert "-no-xattrs" in args and args[-1].startswith("/proc/self/fd/")
    kwargs = cast(dict[str, object], captured["kwargs"])
    assert kwargs["env"] == {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
    assert kwargs["cwd"] == str(staging)
    assert "shell" not in kwargs


def test_incremental_no_buffering_and_limits() -> None:
    from pathlib import Path as _Path

    source = (_Path(__file__).parents[1] / "buildpython/steps/appimage/extraction.py").read_text()
    assert "capture_output" not in source
    assert "selectors.DefaultSelector" in source
    assert "pass_fds" in source
    assert "unsquashfs timed out" in source
    assert "output limit exceeded" in source
    # Post-check is documented as not a barrier; CI runs dedicated container.
    from buildpython.steps.appimage.artifact import LIMITATIONS, SCOPE

    assert "post-hoc" in " ".join(LIMITATIONS).lower()
    assert SCOPE == "finished-appimage/static-runtime-abi"
