"""Provider closure: CXX exports, SONAME, search order, cycles; fakes only."""

from __future__ import annotations

from pathlib import Path

from appimage_artifact_fakes import (
    MappingInspector,
    baseline_text,
    dep_text,
    fake_extractor_factory,
    write_appimage_with_text,
    write_baseline,
)

from buildpython.steps.appimage.artifact import GateReport, audit_artifact


def _baseline_full(tmp_path: Path, mapping: dict[bytes, str]) -> Path:
    root = tmp_path / "baseline"
    libc = baseline_text("libc.so.6", versions=("GLIBC_2.35",), defs=("GLIBC_2.35", "GLIBC_2.2.5"))
    loader = dep_text(
        needed=(), needs_map={}, defs=("GLIBC_PRIVATE",), soname="ld-linux-x86-64.so.2"
    )
    stdcxx = dep_text(
        needed=("libc.so.6",),
        needs_map={"libc.so.6": ("GLIBC_2.35",)},
        defs=("GLIBCXX_3.4", "GLIBCXX_3.4.30", "CXXABI_1.3"),
        soname="libstdc++.so.6",
    )
    mapping[b"bl-libc2"] = libc
    mapping[b"bl-loader2"] = loader
    mapping[b"bl-stdcxx"] = stdcxx
    write_baseline(root, "lib/x86_64-linux-gnu/libc.so.6", text=libc, marker=b"bl-libc2")
    write_baseline(root, "lib64/ld-linux-x86-64.so.2", text=loader, marker=b"bl-loader2")
    write_baseline(
        root, "usr/lib/x86_64-linux-gnu/libstdc++.so.6", text=stdcxx, marker=b"bl-stdcxx"
    )
    return root


def _outer() -> str:
    return dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})


def _run(
    tmp_path: Path,
    bundled: list[tuple[str, bytes, str]],
    baseline: Path,
    outer: str,
    mapping: dict[bytes, str],
) -> GateReport:
    for _, marker, text in bundled:
        mapping[marker] = text
    inspector = MappingInspector(outer, mapping)
    extractor = fake_extractor_factory(bundled)
    art = tmp_path / "dep.AppImage"
    write_appimage_with_text(art, outer)
    return audit_artifact(art, baseline, inspector=inspector, extractor=extractor)


def test_cxx_pass_via_baseline(tmp_path: Path) -> None:
    mapping: dict[bytes, str] = {}
    baseline = _baseline_full(tmp_path, mapping)
    outer = _outer()
    inner = dep_text(
        needed=("libstdc++.so.6", "libc.so.6"),
        needs_map={
            "libstdc++.so.6": ("GLIBCXX_3.4.30", "CXXABI_1.3"),
            "libc.so.6": ("GLIBC_2.35",),
        },
    )
    report = _run(tmp_path, [("usr/lib/app.so", b"cxx-pass", inner)], baseline, outer, mapping)
    assert report.status == "pass", report.errors


def test_cxx_missing_export_fails(tmp_path: Path) -> None:
    mapping: dict[bytes, str] = {}
    baseline = _baseline_full(tmp_path, mapping)
    outer = _outer()
    inner = dep_text(
        needed=("libstdc++.so.6",),
        needs_map={"libstdc++.so.6": ("GLIBCXX_99.0",)},
    )
    report = _run(tmp_path, [("usr/lib/app.so", b"cxx-miss", inner)], baseline, outer, mapping)
    assert report.status == "fail"
    assert "GLIBCXX_99.0" in " ".join(report.errors)


def test_wrong_soname_fails(tmp_path: Path) -> None:
    mapping: dict[bytes, str] = {}
    baseline = _baseline_full(tmp_path, mapping)
    outer = _outer()
    bundled_lib = dep_text(
        needed=("libc.so.6",),
        needs_map={"libc.so.6": ("GLIBC_2.35",)},
        defs=("GLIBC_2.35",),
        soname="libwrong.so.6",
    )
    inner = dep_text(needed=("libfoo.so",), needs_map={"libfoo.so": ("GLIBC_2.35",)})
    bundled = [
        ("usr/lib/libfoo.so", b"wrong-soname", bundled_lib),
        ("usr/lib/app.so", b"app-soname", inner),
    ]
    report = _run(tmp_path, bundled, baseline, outer, mapping)
    assert report.status == "fail"
    assert "SONAME" in " ".join(report.errors)


def test_wrong_class_fails(tmp_path: Path) -> None:
    mapping: dict[bytes, str] = {}
    baseline = _baseline_full(tmp_path, mapping)
    outer = _outer()
    bad = dep_text(
        needed=("libc.so.6",),
        needs_map={"libc.so.6": ("GLIBC_2.35",)},
        elf_class="ELF32",
        soname="libfoo.so",
    )
    inner = dep_text(needed=("libfoo.so",), needs_map={"libfoo.so": ("GLIBC_2.35",)})
    bundled = [("usr/lib/libfoo.so", b"bad-class", bad), ("usr/lib/app.so", b"app-class", inner)]
    report = _run(tmp_path, bundled, baseline, outer, mapping)
    assert report.status == "fail"


def test_rpath_origin_safe_passes(tmp_path: Path) -> None:
    mapping: dict[bytes, str] = {}
    baseline = _baseline_full(tmp_path, mapping)
    outer = _outer()
    provider = dep_text(
        needed=("libc.so.6",),
        needs_map={"libc.so.6": ("GLIBC_2.35",)},
        defs=("EXTRA_1",),
        soname="libextra.so",
    )
    inner = dep_text(
        needed=("libextra.so",), needs_map={"libextra.so": ("EXTRA_1",)}, rpath="$ORIGIN/../lib"
    )
    bundled = [
        ("usr/lib/libextra.so", b"rpath-prov", provider),
        ("usr/bin/app.so", b"rpath-app", inner),
    ]
    report = _run(tmp_path, bundled, baseline, outer, mapping)
    assert report.status == "pass", report.errors


def test_rpath_absolute_and_cwd_fail(tmp_path: Path) -> None:
    for bad in ("/opt/build/lib", ".", "$UNKNOWN/lib", "", "usr/lib", "$ORIGIN/$LIB"):
        mapping: dict[bytes, str] = {}
        baseline = _baseline_full(tmp_path, mapping)
        outer = _outer()
        inner = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)}, rpath=bad)
        report = _run(tmp_path, [("usr/lib/app.so", b"rpath-bad", inner)], baseline, outer, mapping)
        assert report.status == "fail", bad
        assert "RPATH" in " ".join(report.errors)


def test_usrmerge_and_soname_symlinks_resolve(tmp_path: Path) -> None:
    from appimage_artifact_fakes import write_baseline

    mapping: dict[bytes, str] = {}
    root = tmp_path / "baseline"
    libc = baseline_text("libc.so.6", versions=("GLIBC_2.35",), defs=("GLIBC_2.35",))
    loader = dep_text(
        needed=(), needs_map={}, defs=("GLIBC_PRIVATE",), soname="ld-linux-x86-64.so.2"
    )
    foo = dep_text(
        needed=("libc.so.6",),
        needs_map={"libc.so.6": ("GLIBC_2.35",)},
        defs=("FOO_1",),
        soname="libfoo.so.1",
    )
    mapping[b"u-libc"] = libc
    mapping[b"u-loader"] = loader
    mapping[b"u-foo"] = foo
    # Real files only under usr/, lib points via usrmerge.
    write_baseline(root, "usr/lib/x86_64-linux-gnu/libc.so.6", text=libc, marker=b"u-libc")
    write_baseline(root, "usr/lib64/ld-linux-x86-64.so.2", text=loader, marker=b"u-loader")
    write_baseline(root, "usr/lib/x86_64-linux-gnu/libfoo.so.1.2", text=foo, marker=b"u-foo")
    (root / "lib").symlink_to("usr/lib", target_is_directory=True)
    (root / "lib64").symlink_to("usr/lib64", target_is_directory=True)
    (root / "usr/lib/x86_64-linux-gnu/libfoo.so.1").symlink_to("libfoo.so.1.2")
    outer = _outer()
    inner = dep_text(needed=("libfoo.so.1",), needs_map={"libfoo.so.1": ("FOO_1",)})
    mapping[b"u-app"] = inner
    report = _run(
        tmp_path,
        [("usr/lib/app.so", b"u-app", inner)],
        root,
        outer,
        mapping,
    )
    assert report.status == "pass", report.errors


def test_absolute_symlink_inside_root_resolves(tmp_path: Path) -> None:
    from appimage_artifact_fakes import write_baseline

    mapping: dict[bytes, str] = {}
    root = tmp_path / "baseline"
    libc = baseline_text("libc.so.6", versions=("GLIBC_2.35",), defs=("GLIBC_2.35",))
    loader = dep_text(
        needed=(), needs_map={}, defs=("GLIBC_PRIVATE",), soname="ld-linux-x86-64.so.2"
    )
    mapping[b"a-libc"] = libc
    mapping[b"a-loader"] = loader
    write_baseline(root, "usr/lib/x86_64-linux-gnu/libc.so.6", text=libc, marker=b"a-libc")
    write_baseline(root, "lib64/ld-linux-x86-64.so.2", text=loader, marker=b"a-loader")
    (root / "lib").symlink_to("/usr/lib", target_is_directory=True)
    outer = _outer()
    inner = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    mapping[b"a-app"] = inner
    report = _run(tmp_path, [("usr/lib/app.so", b"a-app", inner)], root, outer, mapping)
    assert report.status == "pass", report.errors


def test_baseline_escape_and_cycle_fail(tmp_path: Path) -> None:
    from appimage_artifact_fakes import MappingInspector

    from buildpython.steps.appimage.baseline import BaselineStore

    # Escape via .. beyond root must fail closed, not fallback to host.
    mapping: dict[bytes, str] = {}
    root = tmp_path / "baseline-escape"
    libc = baseline_text("libc.so.6", versions=("GLIBC_2.35",), defs=("GLIBC_2.35",))
    mapping[b"e-libc"] = libc
    (root / "usr/lib").mkdir(parents=True)
    from appimage_artifact_fakes import write_baseline as _write

    _write(root, "usr/lib/libc.so.6", text=libc, marker=b"e-libc")
    (root / "lib").symlink_to("../../outside", target_is_directory=True)
    outer = _outer()
    store = BaselineStore(root, MappingInspector(outer, mapping))
    assert store.load("lib/x86_64-linux-gnu/libc.so.6") is None
    assert "escapes" in " ".join(store.errors).lower() or "escape" in " ".join(store.errors).lower()
    # Cycle.
    mapping2: dict[bytes, str] = {}
    root2 = tmp_path / "baseline-cycle"
    libc2 = baseline_text("libc.so.6", versions=("GLIBC_2.35",), defs=("GLIBC_2.35",))
    mapping2[b"c-libc"] = libc2
    write_baseline(root2, "usr/lib/libc.so.6", text=libc2, marker=b"c-libc")
    (root2 / "a").symlink_to("b")
    (root2 / "b").symlink_to("a")
    outer2 = _outer()
    inner2 = dep_text(needed=("libc.so.6",), needs_map={"libc.so.6": ("GLIBC_2.35",)})
    mapping2[b"c-app"] = inner2
    # Directly exercise loader with cyclic path via custom baseline dir is covered by unit below.
    from appimage_artifact_fakes import MappingInspector

    from buildpython.steps.appimage.baseline import BaselineStore

    store = BaselineStore(root2, MappingInspector(outer2, mapping2))
    assert store.load("a/libc.so.6") is None
    assert "cyclic" in " ".join(store.errors).lower() or "symlink" in " ".join(store.errors).lower()


def test_missing_nested_fails(tmp_path: Path) -> None:
    mapping: dict[bytes, str] = {}
    baseline = _baseline_full(tmp_path, mapping)
    outer = _outer()
    mid = dep_text(
        needed=("libmissing.so", "libc.so.6"),
        needs_map={"libmissing.so": ("MISSING_1",), "libc.so.6": ("GLIBC_2.35",)},
        soname="libmid.so",
        defs=("MID_1",),
    )
    top = dep_text(needed=("libmid.so",), needs_map={"libmid.so": ("MID_1",)})
    bundled = [("usr/lib/libmid.so", b"mid-miss", mid), ("usr/lib/top.so", b"top-miss", top)]
    report = _run(tmp_path, bundled, baseline, outer, mapping)
    assert report.status == "fail"
    assert "missing provider" in " ".join(report.errors).lower()


def test_cycle_terminates(tmp_path: Path) -> None:
    mapping: dict[bytes, str] = {}
    baseline = _baseline_full(tmp_path, mapping)
    outer = _outer()
    text_a = dep_text(
        needed=("libb.so", "libc.so.6"),
        needs_map={"libb.so": ("B_1",), "libc.so.6": ("GLIBC_2.35",)},
        soname="liba.so",
        defs=("A_1",),
    )
    text_b = dep_text(
        needed=("liba.so", "libc.so.6"),
        needs_map={"liba.so": ("A_1",), "libc.so.6": ("GLIBC_2.35",)},
        soname="libb.so",
        defs=("B_1",),
    )
    bundled = [("usr/lib/liba.so", b"cycle-a", text_a), ("usr/lib/libb.so", b"cycle-b", text_b)]
    report = _run(tmp_path, bundled, baseline, outer, mapping)
    assert report.status == "pass", report.errors


def test_ambiguous_providers_fail(tmp_path: Path) -> None:
    mapping: dict[bytes, str] = {}
    baseline = _baseline_full(tmp_path, mapping)
    outer = _outer()
    first = dep_text(
        needed=("libc.so.6",),
        needs_map={"libc.so.6": ("GLIBC_2.35",)},
        defs=("DUP_1",),
        soname="libdup.so",
    )
    second = dep_text(
        needed=("libc.so.6",),
        needs_map={"libc.so.6": ("GLIBC_2.35",)},
        defs=("DUP_2",),
        soname="libdup.so",
    )
    bundled = [
        ("usr/lib/libdup.so", b"dup-one", first),
        ("usr/lib/python3.12/site-packages/PySide6/Qt/lib/libdup.so", b"dup-two", second),
        (
            "usr/lib/app.so",
            b"dup-app",
            dep_text(needed=("libdup.so",), needs_map={"libdup.so": ("DUP_1",)}),
        ),
    ]
    report = _run(tmp_path, bundled, baseline, outer, mapping)
    assert report.status == "fail"
    assert "ambiguous" in " ".join(report.errors).lower()
