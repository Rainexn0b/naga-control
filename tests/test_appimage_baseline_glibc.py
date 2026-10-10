"""Baseline glibc-component PRIVATE allowance; fakes only, no host reads."""

from __future__ import annotations

from pathlib import Path

import pytest
from appimage_artifact_fakes import (
    MappingInspector,
    baseline_text,
    dep_text,
    fake_extractor_factory,
    write_appimage_with_text,
    write_baseline,
)

from buildpython.steps.appimage import elf
from buildpython.steps.appimage.artifact import audit_artifact
from buildpython.steps.appimage.baseline import BaselineStore


def _libm_text() -> str:
    return dep_text(
        needed=("libc.so.6",),
        needs_map={"libc.so.6": ("GLIBC_2.35", "GLIBC_PRIVATE")},
        defs=("GLIBC_2.35",),
        soname="libm.so.6",
    )


def _libresolv_text() -> str:
    return dep_text(
        needed=("libc.so.6",),
        needs_map={"libc.so.6": ("GLIBC_2.35", "GLIBC_PRIVATE")},
        defs=("GLIBC_2.35",),
        soname="libresolv.so.2",
    )


def _baseline_with_libm(tmp_path: Path, mapping: dict[bytes, str]) -> Path:
    root = tmp_path / "baseline"
    libc = baseline_text("libc.so.6", versions=("GLIBC_2.35",), defs=("GLIBC_2.35", "GLIBC_2.2.5"))
    loader = dep_text(
        needed=(), needs_map={}, defs=("GLIBC_PRIVATE",), soname="ld-linux-x86-64.so.2"
    )
    libm = _libm_text()
    mapping[b"glibc-libc"] = libc
    mapping[b"glibc-loader"] = loader
    mapping[b"glibc-libm"] = libm
    write_baseline(root, "lib/x86_64-linux-gnu/libc.so.6", text=libc, marker=b"glibc-libc")
    write_baseline(root, "lib64/ld-linux-x86-64.so.2", text=loader, marker=b"glibc-loader")
    write_baseline(root, "lib/x86_64-linux-gnu/libm.so.6", text=libm, marker=b"glibc-libm")
    return root


def test_baseline_libm_private_closure_passes(tmp_path: Path) -> None:
    mapping: dict[bytes, str] = {}
    baseline = _baseline_with_libm(tmp_path, mapping)
    outer = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    inner = dep_text(
        needed=("libm.so.6", "libc.so.6"),
        needs_map={"libm.so.6": ("GLIBC_2.35",), "libc.so.6": ("GLIBC_2.35",)},
    )
    mapping[b"glibc-app"] = inner
    inspector = MappingInspector(outer, mapping)
    extractor = fake_extractor_factory([("usr/lib/app.so", b"glibc-app", inner)])
    artifact = tmp_path / "libm.AppImage"
    write_appimage_with_text(artifact, outer)
    report = audit_artifact(artifact, baseline, inspector=inspector, extractor=extractor)
    assert report.status == "pass", report.errors


def test_same_private_as_bundled_payload_still_fails() -> None:
    libm = _libm_text()
    with pytest.raises(ValueError, match="GLIBC_PRIVATE or unknown"):
        elf.parse_readelf(libm)
    with pytest.raises(ValueError, match="baseline PRIVATE allowance"):
        elf.parse_baseline_provider(libm, provider_key="libfoo.so")


def test_baseline_libm_provider_key_allows_only_glibc_component() -> None:
    libm = _libm_text()
    allowed = elf.parse_baseline_provider(libm, provider_key="libm.so.6")
    assert allowed.soname == "libm.so.6"
    assert allowed.required_glibc == ("GLIBC_2.35",)


def _baseline_with_resolv(tmp_path: Path, mapping: dict[bytes, str]) -> Path:
    root = tmp_path / "baseline-resolv"
    libc = baseline_text("libc.so.6", versions=("GLIBC_2.35",), defs=("GLIBC_2.35", "GLIBC_2.2.5"))
    loader = dep_text(
        needed=(), needs_map={}, defs=("GLIBC_PRIVATE",), soname="ld-linux-x86-64.so.2"
    )
    resolv = _libresolv_text()
    mapping[b"baseline-resolv-libc"] = libc
    mapping[b"baseline-resolv-loader"] = loader
    mapping[b"baseline-resolv-file-a"] = resolv
    mapping[b"baseline-resolv-file-b"] = resolv
    write_baseline(
        root, "lib/x86_64-linux-gnu/libc.so.6", text=libc, marker=b"baseline-resolv-libc"
    )
    write_baseline(
        root, "lib64/ld-linux-x86-64.so.2", text=loader, marker=b"baseline-resolv-loader"
    )
    write_baseline(
        root,
        "lib/x86_64-linux-gnu/libresolv.so.2",
        text=resolv,
        marker=b"baseline-resolv-file-a",
    )
    write_baseline(
        root,
        "usr/lib/x86_64-linux-gnu/libresolv.so.2",
        text=resolv,
        marker=b"baseline-resolv-file-b",
    )
    return root


def test_baseline_resolv_private_closure_passes(tmp_path: Path) -> None:
    mapping: dict[bytes, str] = {}
    baseline = _baseline_with_resolv(tmp_path, mapping)
    outer = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    inner = dep_text(
        needed=("libresolv.so.2", "libc.so.6"),
        needs_map={"libresolv.so.2": ("GLIBC_2.35",), "libc.so.6": ("GLIBC_2.35",)},
    )
    mapping[b"bundled-resolv-application"] = inner
    inspector = MappingInspector(outer, mapping)
    extractor = fake_extractor_factory([("usr/lib/app.so", b"bundled-resolv-application", inner)])
    artifact = tmp_path / "resolv.AppImage"
    write_appimage_with_text(artifact, outer)
    report = audit_artifact(artifact, baseline, inspector=inspector, extractor=extractor)
    assert report.status == "pass", report.errors


def test_same_resolv_private_as_bundled_payload_still_fails() -> None:
    resolv = _libresolv_text()
    with pytest.raises(ValueError, match="GLIBC_PRIVATE or unknown"):
        elf.parse_readelf(resolv)
    with pytest.raises(ValueError, match="baseline PRIVATE allowance"):
        elf.parse_baseline_provider(resolv, provider_key="libfoo.so.2")


def test_baseline_resolv_provider_key_allows_only_resolv() -> None:
    resolv = _libresolv_text()
    allowed = elf.parse_baseline_provider(resolv, provider_key="libresolv.so.2")
    assert allowed.soname == "libresolv.so.2"
    assert allowed.required_glibc == ("GLIBC_2.35",)
    with pytest.raises(ValueError, match="baseline PRIVATE allowance"):
        elf.parse_baseline_provider(resolv, provider_key="libother.so.1")


def test_baseline_resolv_both_lib_paths_load(tmp_path: Path) -> None:
    mapping: dict[bytes, str] = {}
    baseline = _baseline_with_resolv(tmp_path, mapping)
    outer = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    store = BaselineStore(baseline, MappingInspector(outer, mapping))
    first = store.load("lib/x86_64-linux-gnu/libresolv.so.2")
    second = store.load("usr/lib/x86_64-linux-gnu/libresolv.so.2")
    assert first is not None and second is not None
    assert first.info.soname == "libresolv.so.2"
    assert second.info.soname == "libresolv.so.2"
    assert store.errors == []


def test_unknown_abi_dtrelr_still_rejected() -> None:
    text = dep_text(
        needed=("libc.so.6",),
        needs_map={"libc.so.6": ("GLIBC_ABI_DT_RELR",)},
    )
    with pytest.raises(ValueError, match="GLIBC_PRIVATE or unknown"):
        elf.parse_readelf(text)
    with pytest.raises(ValueError, match=r"GLIBC_PRIVATE or unknown|baseline PRIVATE"):
        elf.parse_baseline_provider(text, provider_key="libc.so.6")


def test_malformed_format_counts_still_rejected() -> None:
    libm = _libm_text()
    assert "contains 1 entries:" in libm
    bad = libm.replace("contains 1 entries:", "contains 2 entries:", 1)
    with pytest.raises(ValueError):
        elf.parse_readelf(bad)
    with pytest.raises(ValueError):
        elf.parse_baseline_provider(bad, provider_key="libm.so.6")


def test_unrelated_baseline_soname_private_still_fails(tmp_path: Path) -> None:
    mapping: dict[bytes, str] = {}
    root = tmp_path / "baseline-other"
    other = dep_text(
        needed=("libc.so.6",),
        needs_map={"libc.so.6": ("GLIBC_PRIVATE",)},
        defs=("OTHER_1",),
        soname="libother.so.1",
    )
    mapping[b"other-priv"] = other
    write_baseline(root, "lib/x86_64-linux-gnu/libother.so.1", text=other, marker=b"other-priv")
    store = BaselineStore(root, MappingInspector(other, mapping))
    assert store.load("lib/x86_64-linux-gnu/libother.so.1") is None
    assert "GLIBC_PRIVATE" in " ".join(store.errors) or "allowance" in " ".join(store.errors)
