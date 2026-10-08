"""Finished artifact outer/runtime checks; fakes only, no host binaries."""

from __future__ import annotations

from pathlib import Path

from appimage_artifact_fakes import (
    MappingInspector,
    baseline_text,
    dep_text,
    fake_extractor_factory,
    header_for,
    superblock,
    write_appimage_with_text,
    write_baseline,
)

from buildpython.steps.appimage.artifact import GateReport, audit_artifact


def _baseline(tmp_path: Path, mapping: dict[bytes, str]) -> Path:
    root = tmp_path / "baseline"
    libc = baseline_text("libc.so.6", versions=("GLIBC_2.35",), defs=("GLIBC_2.35", "GLIBC_2.2.5"))
    loader = dep_text(
        needed=(), needs_map={}, defs=("GLIBC_PRIVATE", "GLIBC_2.35"), soname="ld-linux-x86-64.so.2"
    )
    mapping[b"baseline-libc"] = libc
    mapping[b"baseline-loader"] = loader
    write_baseline(root, "lib/x86_64-linux-gnu/libc.so.6", text=libc, marker=b"baseline-libc")
    write_baseline(root, "lib64/ld-linux-x86-64.so.2", text=loader, marker=b"baseline-loader")
    (root / "lib/x86_64-linux-gnu/libc.so.6").chmod(0o644)
    return root


def _run(tmp_path: Path, outer_text: str, bundled: list[tuple[str, bytes, str]]) -> GateReport:
    mapping: dict[bytes, str] = {}
    baseline = _baseline(tmp_path, mapping)
    for _, marker, text in bundled:
        mapping[marker] = text
    inspector = MappingInspector(outer_text, mapping)
    extractor = fake_extractor_factory(bundled)
    artifact = tmp_path / "Naga-Control-0.4.0-x86_64.AppImage"
    write_appimage_with_text(artifact, outer_text)
    return audit_artifact(artifact, baseline, inspector=inspector, extractor=extractor)


def test_happy_pass(tmp_path: Path) -> None:
    inner = dep_text(
        needed=("libc.so.6",),
        needs_map={"libc.so.6": ("GLIBC_2.35",)},
        defs=(),
        soname="payload.so",
    )
    outer = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    report = _run(tmp_path, outer, [("usr/lib/payload.so", b"inner-ok-pass", inner)])
    assert report.status == "pass", report.errors


def test_inner_high_glibc_fails(tmp_path: Path) -> None:
    inner = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.36",)})
    outer = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    report = _run(tmp_path, outer, [("usr/lib/payload.so", b"inner-high", inner)])
    assert report.status == "fail"
    assert "GLIBC_2.36" in " ".join(report.errors)


def test_outer_high_glibc_fails(tmp_path: Path) -> None:
    inner = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    outer = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.44",)})
    report = _run(tmp_path, outer, [("usr/lib/payload.so", b"inner-ok", inner)])
    assert report.status == "fail"
    assert "GLIBC_2.44" in " ".join(report.errors)


def test_wrong_arch_fails(tmp_path: Path) -> None:
    inner = dep_text(machine="AArch64")
    outer = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    report = _run(tmp_path, outer, [("usr/lib/payload.so", b"inner-arch", inner)])
    assert report.status == "fail"


def test_wrong_loader_fails(tmp_path: Path) -> None:
    inner = dep_text(
        interpreter="/lib/ld-musl-x86_64.so.1", needs_map={"libc.so.6": ("GLIBC_2.35",)}
    )
    outer = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    report = _run(tmp_path, outer, [("usr/lib/payload.so", b"inner-loader", inner)])
    assert report.status == "fail"
    assert "interpreter" in " ".join(report.errors).lower()


def test_truncated_header_fails(tmp_path: Path) -> None:
    mapping: dict[bytes, str] = {}
    baseline = _baseline(tmp_path, mapping)
    outer = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    inspector = MappingInspector(outer, mapping)
    extractor = fake_extractor_factory([])
    artifact = tmp_path / "short.AppImage"
    artifact.write_bytes(b"\x7fELF\x02")
    report = audit_artifact(artifact, baseline, inspector=inspector, extractor=extractor)
    assert report.status == "fail"
    assert "truncated" in " ".join(report.errors).lower() or "ELF" in " ".join(report.errors)


def test_missing_ai02_fails(tmp_path: Path) -> None:
    from appimage_artifact_fakes import outer_header

    mapping: dict[bytes, str] = {}
    baseline = _baseline(tmp_path, mapping)
    outer = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    inspector = MappingInspector(outer, mapping)
    extractor = fake_extractor_factory([])
    artifact = tmp_path / "bad-ai.AppImage"
    header = outer_header(ai02=False, phnum=1, shnum=4)
    data = bytearray(4096 + 8192)
    data[0:64] = header
    data[4096 : 4096 + 96] = superblock()
    artifact.write_bytes(bytes(data))
    report = audit_artifact(artifact, baseline, inspector=inspector, extractor=extractor)
    assert report.status == "fail"
    assert "AI02" in " ".join(report.errors) or "Type2" in " ".join(report.errors)


def test_decoy_invalid_ignored(tmp_path: Path) -> None:
    inner = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    outer = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    mapping: dict[bytes, str] = {}
    baseline = _baseline(tmp_path, mapping)
    mapping[b"inner-decoy"] = inner
    inspector = MappingInspector(outer, mapping)
    bundled = [("usr/lib/payload.so", b"inner-decoy", inner)]
    extractor = fake_extractor_factory(bundled)
    artifact = tmp_path / "decoy.AppImage"
    decoy = superblock(offset_valid=False)
    write_appimage_with_text(artifact, outer, decoys=[(8192, decoy)])
    report = audit_artifact(artifact, baseline, inspector=inspector, extractor=extractor)
    assert report.status == "pass", report.errors


def test_duplicate_valid_fails(tmp_path: Path) -> None:
    inner = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    outer = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    mapping: dict[bytes, str] = {}
    baseline = _baseline(tmp_path, mapping)
    mapping[b"inner-dup"] = inner
    inspector = MappingInspector(outer, mapping)
    bundled = [("usr/lib/payload.so", b"inner-dup", inner)]
    extractor = fake_extractor_factory(bundled)
    artifact = tmp_path / "dup.AppImage"
    write_appimage_with_text(artifact, outer, extra_valid=8192)
    report = audit_artifact(artifact, baseline, inspector=inspector, extractor=extractor)
    assert report.status == "fail"
    assert "multiple" in " ".join(report.errors).lower()


def test_definitions_not_needs_and_static_outer(tmp_path: Path) -> None:
    inner = dep_text(
        needed=("libc.so.6",),
        needs_map={"libc.so.6": ("GLIBC_2.35",)},
        defs=("GLIBC_2.44",),
        soname="payload.so",
    )
    outer = dep_text(needed=(), needs_map={}, defs=())
    _ = header_for(outer)
    report = _run(tmp_path, outer, [("usr/lib/payload.so", b"inner-defs", inner)])
    assert report.status == "pass", report.errors
    assert report.checked == 1


def test_optional_tables_absent_pass(tmp_path: Path) -> None:
    inner = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    outer = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    mapping: dict[bytes, str] = {}
    baseline = _baseline(tmp_path, mapping)
    mapping[b"inner-opt"] = inner
    inspector = MappingInspector(outer, mapping)
    bundled = [("usr/lib/payload.so", b"inner-opt", inner)]
    extractor = fake_extractor_factory(bundled)
    artifact = tmp_path / "opt.AppImage"
    data = superblock(absent=("fragment", "export", "xattr", "id"), fragments=0)
    write_appimage_with_text(artifact, outer, superblock_data=data)
    report = audit_artifact(artifact, baseline, inspector=inspector, extractor=extractor)
    assert report.status == "pass", report.errors


def test_required_table_absent_fails(tmp_path: Path) -> None:
    inner = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    outer = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    mapping: dict[bytes, str] = {}
    baseline = _baseline(tmp_path, mapping)
    mapping[b"inner-req"] = inner
    inspector = MappingInspector(outer, mapping)
    bundled = [("usr/lib/payload.so", b"inner-req", inner)]
    extractor = fake_extractor_factory(bundled)
    artifact = tmp_path / "req.AppImage"
    data = superblock(absent=("inode",), fragments=0)
    write_appimage_with_text(artifact, outer, superblock_data=data)
    report = audit_artifact(artifact, baseline, inspector=inspector, extractor=extractor)
    assert report.status == "fail"
    assert "squashfs" in " ".join(report.errors).lower()


def test_fragment_absent_with_fragments_fails(tmp_path: Path) -> None:
    inner = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    outer = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    mapping: dict[bytes, str] = {}
    baseline = _baseline(tmp_path, mapping)
    mapping[b"inner-frag"] = inner
    inspector = MappingInspector(outer, mapping)
    bundled = [("usr/lib/payload.so", b"inner-frag", inner)]
    extractor = fake_extractor_factory(bundled)
    artifact = tmp_path / "frag.AppImage"
    data = superblock(absent=("fragment",), fragments=1)
    write_appimage_with_text(artifact, outer, superblock_data=data)
    report = audit_artifact(artifact, baseline, inspector=inspector, extractor=extractor)
    assert report.status == "fail"


def test_outer_interpreter_and_high_before_extraction(tmp_path: Path) -> None:
    inner = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    outer = dep_text(
        needed=("libc.so.6",),
        needs_map={"libc.so.6": ("GLIBC_2.35",)},
        interpreter="/lib/ld-musl-x86-64.so.1",
    )
    mapping: dict[bytes, str] = {}
    baseline = _baseline(tmp_path, mapping)
    mapping[b"inner-o"] = inner
    inspector = MappingInspector(outer, mapping)
    called: list[int] = []

    def never(fd: int, offset: int, staging: Path) -> object:
        called.append(1)
        from buildpython.utils.subproc import RunResult

        return RunResult("unsquashfs", "", "", 0)

    artifact = tmp_path / "outer-interp.AppImage"
    write_appimage_with_text(artifact, outer)
    report = audit_artifact(artifact, baseline, inspector=inspector, extractor=never)  # type: ignore[arg-type]
    assert report.status == "fail" and not called
    # High outer also fails before extraction.
    outer_high = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.44",)})
    inspector2 = MappingInspector(outer_high, mapping)
    artifact2 = tmp_path / "outer-high2.AppImage"
    write_appimage_with_text(artifact2, outer_high)
    report2 = audit_artifact(artifact2, baseline, inspector=inspector2, extractor=never)  # type: ignore[arg-type]
    assert report2.status == "fail" and len(called) == 0


def test_boundary_single_not_double_counted(tmp_path: Path) -> None:
    inner = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    outer = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    mapping: dict[bytes, str] = {}
    baseline = _baseline(tmp_path, mapping)
    mapping[b"inner-bound"] = inner
    inspector = MappingInspector(outer, mapping)
    bundled = [("usr/lib/payload.so", b"inner-bound", inner)]
    extractor = fake_extractor_factory(bundled)
    artifact = tmp_path / "boundary.AppImage"
    # Place single valid superblock straddling the 1MB scan boundary.
    boundary = 1024 * 1024 - 48
    write_appimage_with_text(artifact, outer, offset=boundary)
    report = audit_artifact(artifact, baseline, inspector=inspector, extractor=extractor)
    assert report.status == "pass", report.errors
