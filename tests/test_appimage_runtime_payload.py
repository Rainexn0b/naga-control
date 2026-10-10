"""Staged payload trim: unused SDK files go, runtime stays, gate stays strict."""

import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest
from appimage_assembly_fakes import (
    FakeAssembly,
    asset_sources,
    probe_data,
    stage_qt_runtime,
    write,
)

from buildpython.steps.appimage import build, payload, runtime
from buildpython.steps.appimage.payload import PayloadTrimError, trim_staged_payloads

ROOT = Path(__file__).resolve().parents[1]
REMOVED_SPOTS = (
    "PySide6/Qt/qml",
    "PySide6/Qt/plugins/sqldrivers",
    "PySide6/Qt/plugins/qmltooling",
    "PySide6/Qt/plugins/designer",
    "PySide6/Qt/plugins/multimedia",
    "PySide6/Qt/plugins/webview",
    "PySide6/Qt/plugins/sceneparsers",
    "PySide6/Qt/plugins/renderers",
    "PySide6/Qt/plugins/geoservices",
    "PySide6/Qt/plugins/texttospeech",
    "PySide6/Qt/plugins/vectorimageformats",
    "PySide6/Qt/plugins/wayland-graphics-integration-server",
    "PySide6/Qt/plugins/egldeviceintegrations",
    "PySide6/Qt/plugins/platforms/libqeglfs.so",
    "PySide6/Qt/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.so",
    "PySide6/QtQml.abi3.so",
    "PySide6/QtQuick.abi3.so",
    "PySide6/Qt3DCore.abi3.so",
    "PySide6/QtSql.abi3.so",
    "PySide6/QtMultimedia.abi3.so",
    "PySide6/QtNfc.abi3.so",
    "PySide6/QtDesigner.abi3.so",
    "PySide6/QtWebEngineCore.abi3.so",
    "numpy/_core/lib/libnpymath.a",
    "numpy/random/lib/libnpyrandom.a",
)
RETAINED_SPOTS = (
    "PySide6/QtCore.abi3.so",
    "PySide6/QtGui.abi3.so",
    "PySide6/QtWidgets.abi3.so",
    "PySide6/QtNetwork.abi3.so",
    "PySide6/Qt/lib/libQt6Core.so.6",
    "PySide6/Qt/lib/libQt6Gui.so.6",
    "PySide6/Qt/lib/libQt6Widgets.so.6",
    "PySide6/Qt/lib/libQt6Network.so.6",
    "PySide6/Qt/lib/libQt6DBus.so.6",
    "PySide6/Qt/lib/libQt6Svg.so.6",
    "PySide6/Qt/plugins/platforms/libqxcb.so",
    "PySide6/Qt/plugins/platforms/libqwayland.so",
    "PySide6/Qt/plugins/platforms/libqoffscreen.so",
    "PySide6/Qt/plugins/platforms/libqminimal.so",
    "PySide6/Qt/plugins/xcbglintegrations/libqxcb-egl-integration.so",
    "PySide6/Qt/plugins/wayland-shell-integration/libxdg-shell.so",
    "PySide6/Qt/plugins/wayland-graphics-integration-client/libqt-plugin-wayland-egl.so",
    "PySide6/Qt/plugins/wayland-decoration-client/libadwaita.so",
    "PySide6/Qt/plugins/imageformats/libqjpeg.so",
    "PySide6/Qt/plugins/imageformats/libqsvg.so",
    "PySide6/Qt/plugins/imageformats/libqico.so",
    "PySide6/Qt/plugins/iconengines/libqsvgicon.so",
    "PySide6/Qt/plugins/tls/libqopensslbackend.so",
    "PySide6/Qt/plugins/networkinformation/libqnetworkmanager.so",
    "PySide6/Qt/plugins/platformthemes/libqxdgdesktopportal.so",
    "PySide6/Qt/plugins/platforminputcontexts/libibusplatforminputcontextplugin.so",
    "PySide6/Qt/lib/libQt6Bluetooth.so.6",
    "PySide6/Qt/lib/libQt6WebView.so.6",
    "PySide6/Qt/plugins/canbus/libqtsocketcanbus.so",
    "numpy/__init__.py",
    "numpy/_core/_multiarray_umath.cpython-312-x86_64-linux-gnu.so",
    "numpy.libs/libopenblas.so",
    "PySide6-6.11.2.dist-info/METADATA",
    "shiboken6/Shiboken.abi3.so",
)


def staged(tmp_path: Path, **kwargs: str) -> tuple[Path, Path]:
    site = tmp_path / "AppDir/usr/lib/python3.12/site-packages"
    stage_qt_runtime(site, **kwargs)
    return tmp_path / "AppDir", site


@pytest.fixture
def assembly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeAssembly:
    monkeypatch.setattr(build, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(runtime.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(runtime.platform, "system", lambda: "Linux")
    for variable in ("ARCH", "PYVER", "PYTHON_VERSION", "PYTHON_BIN"):
        monkeypatch.delenv(variable, raising=False)
    write(tmp_path / "pyproject.toml", '[project]\nversion = "9.8.7"\n')
    asset_sources(tmp_path)
    write(tmp_path / "base/bin/python3", "base interpreter")
    write(tmp_path / "base/lib/python3.12/os.py", "stdlib")
    write(tmp_path / "base/lib/python3.12/lib-dynload/_test.so", "extension")
    write(tmp_path / "base/lib/libpython3.12.so.1.0", "linked library")
    fake = FakeAssembly(tmp_path)
    monkeypatch.setattr(build, "run", fake.run)
    monkeypatch.setattr(build, "download_appimagetool", fake.download)
    return fake


def test_trim_removes_unused_families_and_retains_runtime(tmp_path: Path) -> None:
    appdir, site = staged(tmp_path)
    report = trim_staged_payloads(appdir=appdir, python_version="3.12")
    assert len(report.removed) > 40
    for relative in REMOVED_SPOTS:
        assert not (site / relative).exists(), relative
    assert not (site / "PySide6/Qt/qml/Qt/labs/assetdownloader").exists()
    assert not list((site / "PySide6").glob("libpyside6qml*"))
    assert (site / "PySide6/QtQml.pyi").exists() is False
    for relative in RETAINED_SPOTS:
        assert (site / relative).is_file(), relative
    assert len(list((site / "PySide6/Qt/lib").glob("libicuuc.so.*"))) == 1
    assert "PySide6/Qt/qml" in report.removed
    assert "PySide6/Qt/plugins/sqldrivers" in report.removed
    assert "numpy/_core/lib/libnpymath.a" in report.removed


def test_trim_supports_612_layout_and_versioned_names(tmp_path: Path) -> None:
    appdir, site = staged(tmp_path, support_suffix="6.12", icu_suffix="74")
    report = trim_staged_payloads(appdir=appdir, python_version="3.12")
    assert not list((site / "PySide6").glob("libpyside6qml*"))
    assert len(list((site / "PySide6").glob("libpyside6.abi3.so.*"))) == 1
    assert len(list((site / "PySide6/Qt/lib").glob("libicuuc.so.*"))) == 1
    assert not (site / "PySide6/Qt/lib/libQt6Qml.so.6").exists()
    assert (site / "PySide6/Qt/lib/libQt6Core.so.6").is_file()
    assert "numpy/random/lib/libnpyrandom.a" in report.removed


def test_build_trims_staging_before_tool_assembly(
    assembly: FakeAssembly, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, bool] = {}
    original = assembly.download

    def download(*, work: Path, arch: str) -> Path:
        site = work / "AppDir/usr/lib/python3.12/site-packages"
        seen["trimmed"] = (
            not (site / "PySide6/Qt/qml").exists()
            and not (site / "numpy/_core/lib/libnpymath.a").exists()
            and not (site / "PySide6/QtQml.abi3.so").exists()
            and (site / "PySide6/QtCore.abi3.so").is_file()
            and (site / "PySide6/Qt/plugins/platforms/libqxcb.so").is_file()
            and (site / "numpy/__init__.py").is_file()
        )
        return original(work=work, arch=arch)

    monkeypatch.setattr(build, "download_appimagetool", download)
    assert build.appimage_build_runner().exit_code == 0
    assert seen.get("trimmed") is True


def test_missing_required_component_fails_trim(tmp_path: Path) -> None:
    appdir, site = staged(tmp_path)
    (site / "PySide6/Qt/plugins/platforms/libqxcb.so").unlink()
    with pytest.raises(PayloadTrimError, match="libqxcb"):
        trim_staged_payloads(appdir=appdir, python_version="3.12")


def test_missing_required_component_fails_build(assembly: FakeAssembly) -> None:
    assembly.drop = ("PySide6/Qt/plugins/platforms/libqxcb.so",)
    result = build.appimage_build_runner()
    assert result.exit_code != 0
    assert "libqxcb" in result.stderr
    assert not build.appimage_path().exists()


def test_product_imports_match_retained_bindings() -> None:
    found: set[str] = set()
    pattern = re.compile(r"^\s*(?:from|import)\s+(PySide6\.\w+)", re.MULTILINE)
    for source in (ROOT / "src").rglob("*.py"):
        for match in pattern.finditer(source.read_text(encoding="utf-8")):
            found.add(match.group(1).split(".")[1])
    assert (
        found == set(payload.RETAINED_QT_BINDINGS) == {"QtCore", "QtGui", "QtWidgets", "QtNetwork"}
    )


def _snapshot(directory: Path) -> dict[str, str]:
    digest: dict[str, str] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file() and not path.is_symlink():
            digest[path.relative_to(directory).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return digest


def test_staging_leaves_source_venv_byte_identical(tmp_path: Path) -> None:
    data = probe_data(tmp_path)
    info = runtime.runtime_info(json.dumps(data), arch="x86_64")
    write(info.executable, "base")
    write(info.stdlib / "os.py", "stdlib")
    write(info.dynload / "_test.so", "extension")
    venv = tmp_path / "venv"
    site = venv / "lib/python3.12/site-packages"
    write(site / "dbus/__init__.py", "bundled dbus")
    stage_qt_runtime(site)
    before = _snapshot(venv)
    runtime.copy_runtime(appdir=tmp_path / "AppDir", venv=venv, info=info, libpython=None)
    assert _snapshot(venv) == before


def test_eglfs_backend_removed_while_desktop_plugins_retained(tmp_path: Path) -> None:
    appdir, site = staged(tmp_path)
    report = trim_staged_payloads(appdir=appdir, python_version="3.12")
    for relative in (
        "PySide6/Qt/plugins/platforms/libqeglfs.so",
        "PySide6/Qt/plugins/egldeviceintegrations",
        "PySide6/Qt/lib/libQt6EglFSDeviceIntegration.so.6",
        "PySide6/Qt/lib/libQt6EglFsKmsSupport.so.6",
    ):
        assert not (site / relative).exists(), relative
    for relative in (
        "PySide6/Qt/plugins/platforms/libqxcb.so",
        "PySide6/Qt/plugins/platforms/libqwayland.so",
        "PySide6/Qt/plugins/platforms/libqoffscreen.so",
        "PySide6/Qt/plugins/platforms/libqminimal.so",
        "PySide6/Qt/plugins/xcbglintegrations/libqxcb-egl-integration.so",
        "PySide6/Qt/plugins/xcbglintegrations/libqxcb-glx-integration.so",
        "PySide6/Qt/plugins/wayland-graphics-integration-client/libqt-plugin-wayland-egl.so",
        "PySide6/Qt/plugins/wayland-shell-integration/libxdg-shell.so",
        "PySide6/Qt/plugins/platformthemes/libqgtk3.so",
    ):
        assert (site / relative).is_file(), relative
    assert "PySide6/Qt/plugins/platforms/libqeglfs.so" in report.removed


def test_unknown_native_stays_for_strict_gate(tmp_path: Path) -> None:
    appdir, site = staged(tmp_path)
    traps = (
        "PySide6/Qt/lib/libQt6Mystery.so.6",
        "PySide6/Qt/lib/libswMystery.so",
        "PySide6/Qt/lib/libVendorQuickBridge.so",
        "PySide6/Qt/plugins/mystery/libqmystery.so",
        "numpy/_core/lib/libmystery.a",
    )
    for relative in traps:
        write(site / relative, "unknown native")
    report = trim_staged_payloads(appdir=appdir, python_version="3.12")
    for relative in traps:
        assert (site / relative).is_file(), relative
        assert relative not in report.removed


def test_symlink_escape_is_refused_without_touching_outside(tmp_path: Path) -> None:
    appdir, site = staged(tmp_path)
    outside = tmp_path / "outside"
    write(outside / "keep.txt", "untouched")
    target = site / "PySide6/Qt"
    for child in (target / "lib", target / "plugins", target / "qml", target / "libexec"):
        if child.is_symlink() or child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)
    target.rmdir()
    target.symlink_to(outside, target_is_directory=True)
    with pytest.raises(PayloadTrimError, match="directory link not allowed"):
        trim_staged_payloads(appdir=appdir, python_version="3.12")
    assert (outside / "keep.txt").read_text() == "untouched"
    assert target.is_symlink()


def test_symlink_appdir_root_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "real"
    site = real / "usr/lib/python3.12/site-packages"
    stage_qt_runtime(site)
    link = tmp_path / "AppDir"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(PayloadTrimError, match="must not be a symlink"):
        trim_staged_payloads(appdir=link, python_version="3.12")
    assert (site / "PySide6/QtQml.abi3.so").is_file()
    assert (site / "PySide6/QtCore.abi3.so").is_file()


def test_internal_parent_alias_blocks_before_any_removal(tmp_path: Path) -> None:
    appdir, site = staged(tmp_path)
    stash = site / "stash"
    write(stash / "precious.txt", "unrelated product file")
    target = site / "PySide6/Qt"
    for child in ("lib", "plugins", "qml", "libexec"):
        shutil.rmtree(target / child)
    target.rmdir()
    target.symlink_to(stash, target_is_directory=True)
    with pytest.raises(PayloadTrimError, match="directory link not allowed"):
        trim_staged_payloads(appdir=appdir, python_version="3.12")
    assert (site / "PySide6/QtQml.abi3.so").is_file()
    assert (stash / "precious.txt").read_text() == "unrelated product file"
    assert target.is_symlink()


def test_required_leaf_symlink_outside_is_refused(tmp_path: Path) -> None:
    appdir, site = staged(tmp_path)
    outside = tmp_path / "outside"
    write(outside / "evil.so", "outside bytes")
    leaf = site / "PySide6/Qt/plugins/platforms/libqxcb.so"
    leaf.unlink()
    leaf.symlink_to(outside / "evil.so")
    with pytest.raises(PayloadTrimError, match="escapes AppDir"):
        trim_staged_payloads(appdir=appdir, python_version="3.12")
    assert (outside / "evil.so").read_text() == "outside bytes"
    assert leaf.is_symlink()


def test_required_wildcard_leaf_outside_is_refused(tmp_path: Path) -> None:
    appdir, site = staged(tmp_path)
    outside = tmp_path / "outside"
    write(outside / "evil.so", "outside bytes")
    leaf = site / "PySide6/libpyside6.abi3.so.6.11"
    leaf.unlink()
    leaf.symlink_to(outside / "evil.so")
    with pytest.raises(PayloadTrimError, match="escapes AppDir"):
        trim_staged_payloads(appdir=appdir, python_version="3.12")
    assert (outside / "evil.so").read_text() == "outside bytes"


def test_required_glob_directory_does_not_count(tmp_path: Path) -> None:
    appdir, site = staged(tmp_path)
    leaf = site / "PySide6/Qt/lib/libicuuc.so.73"
    leaf.unlink()
    (site / "PySide6/Qt/lib/libicuuc.so.73").mkdir()
    with pytest.raises(PayloadTrimError, match="libicuuc"):
        trim_staged_payloads(appdir=appdir, python_version="3.12")


def test_required_glob_validates_every_match_in_order(tmp_path: Path) -> None:
    appdir, site = staged(tmp_path)
    outside = tmp_path / "outside"
    write(outside / "evil.so", "outside bytes")
    evil = site / "PySide6/libpyside6.abi3.so.zzz"
    evil.symlink_to(outside / "evil.so")
    assert (site / "PySide6/libpyside6.abi3.so.6.11").is_file()
    with pytest.raises(PayloadTrimError, match="escapes AppDir"):
        trim_staged_payloads(appdir=appdir, python_version="3.12")
    assert (outside / "evil.so").read_text() == "outside bytes"


def test_trim_is_idempotent(tmp_path: Path) -> None:
    appdir, _site = staged(tmp_path)
    first = trim_staged_payloads(appdir=appdir, python_version="3.12")
    assert first.removed
    second = trim_staged_payloads(appdir=appdir, python_version="3.12")
    assert second.removed == ()


@pytest.mark.parametrize("mode", ["outside", "internal"])
def test_libexec_directory_symlink_blocked_before_any_removal(tmp_path: Path, mode: str) -> None:
    appdir, site = staged(tmp_path)
    libexec = site / "PySide6/Qt/libexec"
    assert (site / "PySide6/QtQml.abi3.so").is_file()
    assert (libexec / "rcc").is_file()
    if mode == "outside":
        target = tmp_path / "outside"
        write(target / "rcc", "outside rcc")
        write(target / "uic", "outside uic")
        write(target / "keep.txt", "untouched")
    else:
        target = site / "stash"
        write(target / "rcc", "unrelated product file")
        write(target / "precious.txt", "unrelated product file")
    before = {path.name: path.read_bytes() for path in sorted(target.iterdir())}
    shutil.rmtree(libexec)
    libexec.symlink_to(target, target_is_directory=True)
    with pytest.raises(PayloadTrimError):
        trim_staged_payloads(appdir=appdir, python_version="3.12")
    assert {path.name: path.read_bytes() for path in sorted(target.iterdir())} == before
    assert (site / "PySide6/QtQml.abi3.so").is_file()
    assert libexec.is_symlink()
