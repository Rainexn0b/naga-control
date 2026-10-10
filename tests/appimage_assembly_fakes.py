"""Shared assembly fakes for AppImage build tests (fake commands only)."""

import json
import shlex
from dataclasses import dataclass, field
from pathlib import Path

from buildpython.steps.appimage import assets
from buildpython.utils.subproc import RunResult


def write(path: Path, content: str = "fixture") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def asset_sources(root: Path) -> None:
    for relative in assets.SYSTEM_TEMPLATES:
        write(root / "system" / relative, relative)
    for size in assets.ICON_SIZES:
        write(root / f"assets/icons/hicolor/{size}x{size}/apps/{assets.APP_ID}.png", str(size))
    write(root / f"assets/{assets.APP_ID}.svg", "svg")
    write(root / "buildpython/steps/appimage/AppRun", "#!/bin/sh\n")
    write(root / "buildpython/steps/appimage/probe-shutdown.py")
    write(root / "system/desktop/build.py")
    write(root / "assets/icons/hicolor/unwanted.txt")


def probe_data(root: Path) -> dict[str, object]:
    return {
        "implementation": "cpython",
        "platform": "linux",
        "arch": "x86_64",
        "bits": 64,
        "version": [3, 12],
        "full_version": "3.12.0",
        "executable": str(root / "base/bin/python3"),
        "stdlib": str(root / "base/lib/python3.12"),
        "dynload": str(root / "base/lib/python3.12/lib-dynload"),
        "platlibdir": "lib",
        "gil_disabled": False,
    }


def stage_qt_runtime(site: Path, *, support_suffix: str = "6.11", icu_suffix: str = "73") -> None:
    """Stage representative required + unused Qt/NumPy files (fake contents).

    Mirrors the upstream wheel layout read from the local Qt 6.11 install
    and the CI Qt 6.12 artifact inventory: ``support_suffix`` selects the
    ``libpyside6``/``libshiboken6`` version suffix for either style.
    """
    required = [
        "PySide6/__init__.py",
        "shiboken6/Shiboken.abi3.so",
        f"shiboken6/libshiboken6.abi3.so.{support_suffix}",
        f"PySide6/libpyside6.abi3.so.{support_suffix}",
        "numpy/__init__.py",
        "numpy/_core/_multiarray_umath.cpython-312-x86_64-linux-gnu.so",
        "numpy.libs/libopenblas.so",
        "PySide6-6.11.2.dist-info/METADATA",
    ]
    required.extend(
        f"PySide6/Qt{module}.abi3.so" for module in ("Core", "Gui", "Widgets", "Network")
    )
    required.extend(f"PySide6/Qt{module}.pyi" for module in ("Core", "Gui", "Widgets", "Network"))
    required.extend(
        f"PySide6/Qt/lib/{name}.so.6"
        for name in (
            "libQt6Core",
            "libQt6Gui",
            "libQt6Widgets",
            "libQt6Network",
            "libQt6DBus",
            "libQt6Svg",
        )
    )
    required.extend(
        f"PySide6/Qt/lib/libicu{name}.so.{icu_suffix}" for name in ("uc", "i18n", "data")
    )
    required.extend(
        f"PySide6/Qt/plugins/{path}"
        for path in (
            "platforms/libqxcb.so",
            "platforms/libqwayland.so",
            "platforms/libqoffscreen.so",
            "platforms/libqminimal.so",
            "xcbglintegrations/libqxcb-egl-integration.so",
            "xcbglintegrations/libqxcb-glx-integration.so",
            "wayland-shell-integration/libfullscreen-shell-v1.so",
            "wayland-shell-integration/libivi-shell.so",
            "wayland-shell-integration/libqt-shell.so",
            "wayland-shell-integration/libwl-shell-plugin.so",
            "wayland-shell-integration/libxdg-shell.so",
            "wayland-graphics-integration-client/libdmabuf-server.so",
            "wayland-graphics-integration-client/libdrm-egl-server.so",
            "wayland-graphics-integration-client/libqt-plugin-wayland-egl.so",
            "wayland-graphics-integration-client/libshm-emulation-server.so",
            "wayland-graphics-integration-client/libvulkan-server.so",
            "wayland-decoration-client/libadwaita.so",
            "wayland-decoration-client/libbradient.so",
            "imageformats/libqjpeg.so",
            "imageformats/libqsvg.so",
            "imageformats/libqico.so",
            "iconengines/libqsvgicon.so",
            "tls/libqopensslbackend.so",
            "tls/libqcertonlybackend.so",
            "networkinformation/libqconnman.so",
            "networkinformation/libqglib.so",
            "networkinformation/libqnetworkmanager.so",
            "platformthemes/libqxdgdesktopportal.so",
            "platformthemes/libqgtk3.so",
            "platforminputcontexts/libcomposeplatforminputcontextplugin.so",
            "platforminputcontexts/libibusplatforminputcontextplugin.so",
        )
    )
    # Retained but unlisted: proves the filter does not overreach.
    required.extend(
        f"PySide6/Qt/{path}"
        for path in (
            "lib/libQt6Bluetooth.so.6",
            "lib/libQt6Pdf.so.6",
            "lib/libQt6WebView.so.6",
            "lib/libQt6WebSockets.so.6",
            "plugins/canbus/libqtsocketcanbus.so",
            "plugins/imageformats/libqgif.so",
            "plugins/printsupport/libcupsprintersupport.so",
        )
    )
    unused = [
        f"PySide6/libpyside6qml.abi3.so.{support_suffix}",
        "PySide6/QtQml.pyi",
        "PySide6/QtQuick.pyi",
        "PySide6/QtQml.pyi",
        "PySide6/assistant",
        "PySide6/designer",
        "PySide6/qmllint",
        "PySide6/include/QtCore/qglobal.h",
        "shiboken6/include/shiboken.h",
        "PySide6/Qt/libexec/QtWebEngineProcess",
        "PySide6/Qt/libexec/rcc",
        "PySide6/Qt/qml/QtQuick/libqtquick2plugin.so",
        "PySide6/Qt/qml/QtQuick/qmldir",
        "PySide6/Qt/qml/Qt/labs/assetdownloader/libqmlassetdownloaderprivateplugin.a",
        "PySide6/Qt/qml/Qt/labs/assetdownloader/objects-RelWithDebInfo/x/qrc_init.cpp.o",
        "PySide6/Qt/qml/Qt/labs/assetdownloader/objects-RelWithDebInfo/y/plugin_init.cpp.o",
        "PySide6/Qt/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.so",
        "numpy/_core/lib/libnpymath.a",
        "numpy/random/lib/libnpyrandom.a",
    ]
    unused.extend(
        f"PySide6/Qt{module}.abi3.so"
        for module in (
            "Qml",
            "Quick",
            "QuickWidgets",
            "QmlFeatures",
            "3DCore",
            "Sql",
            "Multimedia",
            "MultimediaWidgets",
            "Nfc",
            "Designer",
            "WebEngineCore",
            "WebEngineWidgets",
        )
    )
    unused.extend(
        f"PySide6/Qt/lib/{name}"
        for name in (
            "libQt63DCore.so.6",
            "libQt6Qml.so.6",
            "libQt6Quick.so.6",
            "libQt6LabsPlatform.so.6",
            "libQt6Sql.so.6",
            "libQt6Multimedia.so.6",
            "libQt6FFmpegStub-ssl.so.3",
            "libavcodec.so.61",
            "libQt6WebEngineCore.so.6",
            "libQt6WebChannel.so.6",
            "libQt6WebViewQuick.so.6",
            "libQt6Help.so.6",
            "libQt6Location.so.6",
            "libQt6TextToSpeech.so.6",
            "libQt6SpatialAudio.so.6",
            "libQt6VirtualKeyboard.so.6",
            "libQt6VirtualKeyboardQml.so.6",
            "libQt6WaylandCompositor.so.6",
            "libQt6CanvasPainter.so.6",
            "libQt6Graphs.so.6",
            "libQt6Lottie.so.6",
            "libQt6EglFSDeviceIntegration.so.6",
            "libQt6EglFsKmsSupport.so.6",
        )
    )
    unused.extend(
        f"PySide6/Qt/plugins/{path}"
        for path in (
            "designer/libPySidePlugin.so",
            "multimedia/libffmpegmediaplugin.so",
            "qmltooling/libqmldbg_tcp.so",
            "qmllint/libqdslintplugin.so",
            "egldeviceintegrations/libqeglfs-kms-integration.so",
            "platforms/libqeglfs.so",
            "sqldrivers/libqsqlite.so",
            "sqldrivers/libqsqloci.so",
            "sqldrivers/libqsqlpsql.so",
            "sqldrivers/libqsqlmysql.so",
            "sqldrivers/libqsqlodbc.so",
            "sqldrivers/libqsqlmimer.so",
            "sqldrivers/libqsqlibase.so",
            "webview/libqtwebview_webengine.so",
            "assetimporters/libassimp.so",
            "geometryloaders/libdefaultgeometryloader.so",
            "sceneparsers/libgltfsceneimport.so",
            "renderers/librhirenderer.so",
            "renderplugins/libscene2d.so",
            "geoservices/libqtgeoservices_osm.so",
            "scxmldatamodel/libqscxmlecmascriptdatamodel.so",
            "texttospeech/libqtexttospeech_speechd.so",
            "vectorimageformats/libqlottievectorimage.so",
            "wayland-graphics-integration-server/libqt-wayland-compositor-shm-emulation-server.so",
        )
    )
    for relative in (*required, *unused):
        if not (site / relative).exists():
            write(site / relative, relative)


@dataclass
class FakeAssembly:
    root: Path
    calls: list[list[str]] = field(default_factory=list[list[str]])
    failure: str = ""
    produce_artifact: bool = True
    produce_wheel: bool = True
    empty_artifact: bool = False
    drop: tuple[str, ...] = ()
    support_suffix: str = "6.11"

    def run(self, args: list[str], *, cwd: str, env_overrides: dict[str, str]) -> RunResult:
        assert cwd == str(self.root)
        assert env_overrides == {"ARCH": "x86_64", "PYTHONNOUSERSITE": "1"}
        self.calls.append(args)
        label = "probe" if "-c" in args else args[args.index("-m") + 1] if "-m" in args else args[0]
        if self.failure == label:
            if "--appimage-extract-and-run" in args:
                write(Path(args[-1]), "partial image")
            return RunResult(shlex.join(args), "complete failing stdout\n", "complete stderr\n", 23)
        stdout = f"{label} stdout\n"
        if label == "probe":
            stdout = json.dumps(probe_data(self.root))
        elif label == "build" and self.produce_wheel:
            write(self.root / "build/appimage/naga_control-9.8.7-py3-none-any.whl")
        elif label == "venv":
            write(Path(args[-1]) / "lib/python3.12/site-packages/PySide6/__init__.py", "bundled Qt")
            write(Path(args[-1]) / "lib/python3.12/site-packages/dbus/__init__.py", "bundled dbus")
            site = Path(args[-1]) / "lib/python3.12/site-packages"
            stage_qt_runtime(site, support_suffix=self.support_suffix)
            for relative in self.drop:
                target = site / relative
                if target.is_file() or target.is_symlink():
                    target.unlink()
        elif label == "ldd":
            stdout = f"libpython3.12.so.1.0 => {self.root}/base/lib/libpython3.12.so.1.0 (0x123)\n"
        elif "--appimage-extract-and-run" in args and self.produce_artifact:
            write(Path(args[-1]), "" if self.empty_artifact else "new image")
        return RunResult(shlex.join(args), stdout, f"{label} stderr\n", 0)

    def download(self, *, work: Path, arch: str) -> Path:
        assert work == self.root / "build/appimage"
        assert arch == "x86_64"
        return write(work / "appimagetool", "tool")
