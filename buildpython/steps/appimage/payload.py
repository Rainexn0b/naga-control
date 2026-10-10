"""Trim unused third-party SDK payloads from a staged AppDir (staging only).

Runs at the end of ``copy_runtime``: after dependencies are copied, before
AppImage assembly. Only Naga's Qt modules are selected: the product imports
exactly ``QtCore``, ``QtGui``, ``QtWidgets`` and ``QtNetwork`` (verified by
test), so every other Python Qt binding plus the unused QML, 3D, Designer,
NFC, SQL, WebEngine, Multimedia, EGLFS and tool payloads are removed from
staging.

Native-library removals follow the read-only DT_NEEDED closure measured on
the upstream wheels: a retained object never needs a removed ``libQt6*``
object. QML/Quick matching applies only to ``libQt6*`` components and the
bundled FFmpeg set is an explicit stem list, so unknown vendor libraries
stay in place for the strict static gate (as do unexpected ``.a``/``.o``
elsewhere and unlisted modules). NumPy runtime objects and ``numpy.libs``
are always retained; only the two known static SDK archives are removed.
The source venv is never written.

Confinement: the AppDir itself must be a real directory, every staging
path ancestor must be a real directory (no directory symlinks, contained
or escaping), and allowed leaf file symlinks are only unlinked or counted
when their resolved target is a regular file inside the AppDir.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

#: Python Qt bindings imported anywhere under ``src/`` (scanned by test).
RETAINED_QT_BINDINGS = ("QtCore", "QtGui", "QtWidgets", "QtNetwork")

#: Basename prefixes of unused native libraries directly under Qt/lib.
_LIB_PREFIXES = (
    "libQt63D",
    "libQt6Designer",
    "libQt6Nfc",
    "libQt6Labs",
    "libQt6Sql",
    "libQt6Multimedia",
    "libQt6FFmpegStub",
    "libQt6WebEngine",
    "libQt6WebChannel",
    "libpyside6qml",
    "libQt6Graphs",
    "libQt6Lottie",
    "libQt6CanvasPainter",
    "libQt6Help",
    "libQt6Location",
    "libQt6TextToSpeech",
    "libQt6SpatialAudio",
    "libQt6VirtualKeyboard",
    "libQt6WaylandCompositor",
    "libQt6EglFSDeviceIntegration",
    "libQt6EglFsKms",
)

#: Known bundled FFmpeg stems (versioned ``.so`` suffixes accepted).
_FFMPEG_STEMS = (
    "libavcodec",
    "libavdevice",
    "libavfilter",
    "libavformat",
    "libavutil",
    "libswresample",
    "libswscale",
)

#: Exact basenames not covered by the rules above.
_LIB_EXACT = {
    "libQt6WebViewQuick.so.6",
    "libQt6WaylandEglCompositorHwIntegration.so.6",
}

#: Plugin directories with no retained consumer (checked against DT_NEEDED).
#: ``egldeviceintegrations`` serves only the removed EGLFS backend; all
#: xcb/wayland-client desktop plugins stay.
_PLUGIN_DIRS = (
    "assetimporters",
    "designer",
    "egldeviceintegrations",
    "geometryloaders",
    "geoservices",
    "multimedia",
    "qmllint",
    "qmltooling",
    "renderers",
    "renderplugins",
    "sceneparsers",
    "scxmldatamodel",
    "sqldrivers",
    "texttospeech",
    "vectorimageformats",
    "wayland-graphics-integration-server",
    "webview",
)

#: Unused EGLFS platform plugin (embedded framebuffer; desktop uses xcb/wayland).
_EGLFS_PLATFORM_PLUGIN = ("PySide6", "Qt", "plugins", "platforms", "libqeglfs.so")

#: Host/build tool executables, never loaded at runtime.
_TOP_TOOLS = (
    "assistant",
    "balsam",
    "balsamui",
    "designer",
    "linguist",
    "lrelease",
    "lupdate",
    "qmlformat",
    "qmllint",
    "qmlls",
    "qsb",
    "svgtoqml",
)
_LIBEXEC_TOOLS = (
    "QtWebEngineProcess",
    "qmlcachegen",
    "qmlimportscanner",
    "qmltyperegistrar",
    "rcc",
    "uic",
)

#: Known unused static SDK archives (exact staging-relative paths).
_STATIC_ARCHIVES = (
    "numpy/_core/lib/libnpymath.a",
    "numpy/random/lib/libnpyrandom.a",
)

#: Required files, relative to site-packages; ``*`` entries are one-level globs.
_REQUIRED = (
    "PySide6/QtCore.abi3.so",
    "PySide6/QtGui.abi3.so",
    "PySide6/QtWidgets.abi3.so",
    "PySide6/QtNetwork.abi3.so",
    "PySide6/libpyside6.abi3.so.*",
    "shiboken6/Shiboken.abi3.so",
    "shiboken6/libshiboken6.abi3.so.*",
    "PySide6/Qt/lib/libQt6Core.so.6",
    "PySide6/Qt/lib/libQt6Gui.so.6",
    "PySide6/Qt/lib/libQt6Widgets.so.6",
    "PySide6/Qt/lib/libQt6Network.so.6",
    "PySide6/Qt/lib/libQt6DBus.so.6",
    "PySide6/Qt/lib/libQt6Svg.so.6",
    "PySide6/Qt/lib/libicuuc.so.*",
    "PySide6/Qt/lib/libicui18n.so.*",
    "PySide6/Qt/lib/libicudata.so.*",
    "PySide6/Qt/plugins/platforms/libqxcb.so",
    "PySide6/Qt/plugins/platforms/libqwayland.so",
    "PySide6/Qt/plugins/platforms/libqoffscreen.so",
    "PySide6/Qt/plugins/platforms/libqminimal.so",
    "PySide6/Qt/plugins/xcbglintegrations/libqxcb-egl-integration.so",
    "PySide6/Qt/plugins/xcbglintegrations/libqxcb-glx-integration.so",
    "PySide6/Qt/plugins/wayland-shell-integration/libfullscreen-shell-v1.so",
    "PySide6/Qt/plugins/wayland-shell-integration/libivi-shell.so",
    "PySide6/Qt/plugins/wayland-shell-integration/libqt-shell.so",
    "PySide6/Qt/plugins/wayland-shell-integration/libwl-shell-plugin.so",
    "PySide6/Qt/plugins/wayland-shell-integration/libxdg-shell.so",
    "PySide6/Qt/plugins/wayland-graphics-integration-client/libdmabuf-server.so",
    "PySide6/Qt/plugins/wayland-graphics-integration-client/libdrm-egl-server.so",
    "PySide6/Qt/plugins/wayland-graphics-integration-client/libqt-plugin-wayland-egl.so",
    "PySide6/Qt/plugins/wayland-graphics-integration-client/libshm-emulation-server.so",
    "PySide6/Qt/plugins/wayland-graphics-integration-client/libvulkan-server.so",
    "PySide6/Qt/plugins/wayland-decoration-client/libadwaita.so",
    "PySide6/Qt/plugins/wayland-decoration-client/libbradient.so",
    "PySide6/Qt/plugins/imageformats/libqjpeg.so",
    "PySide6/Qt/plugins/imageformats/libqsvg.so",
    "PySide6/Qt/plugins/imageformats/libqico.so",
    "PySide6/Qt/plugins/iconengines/libqsvgicon.so",
    "PySide6/Qt/plugins/tls/libqopensslbackend.so",
    "PySide6/Qt/plugins/tls/libqcertonlybackend.so",
    "PySide6/Qt/plugins/networkinformation/libqconnman.so",
    "PySide6/Qt/plugins/networkinformation/libqglib.so",
    "PySide6/Qt/plugins/networkinformation/libqnetworkmanager.so",
    "PySide6/Qt/plugins/platformthemes/libqxdgdesktopportal.so",
    "PySide6/Qt/plugins/platformthemes/libqgtk3.so",
    "PySide6/Qt/plugins/platforminputcontexts/libcomposeplatforminputcontextplugin.so",
    "PySide6/Qt/plugins/platforminputcontexts/libibusplatforminputcontextplugin.so",
    "numpy/__init__.py",
)


class PayloadTrimError(ValueError):
    """Staged payload is unsafe to trim or misses a required component."""


@dataclass(frozen=True)
class TrimReport:
    removed: tuple[str, ...]


def _within(root: Path, candidate: Path) -> Path:
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise PayloadTrimError(f"staged link escapes AppDir: {candidate}")
    return resolved


def _scope(root: Path, *parts: str) -> Path:
    """Join ``parts`` under ``root``, rejecting symlink directory ancestors.

    Every intermediate component must be a real directory; a symlinked leaf
    passes through for the caller to validate (file links may be allowed,
    directory links never are).
    """
    node = root
    for index, part in enumerate(parts):
        if not part or part in (".", "..") or "/" in part or "\\" in part:
            raise PayloadTrimError(f"unsupported staged path component: {part!r}")
        node = node / part
        if index < len(parts) - 1 and node.is_symlink():
            raise PayloadTrimError(f"staged directory link not allowed: {node}")
    return node


def _ancestors(root: Path, path: Path) -> None:
    """Reject lexical escape and symlink directory ancestors via ``_scope``."""
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        raise PayloadTrimError(f"staged path escapes AppDir: {path}") from None
    _scope(root, *parts)


def _leaf_link_target(root: Path, path: Path) -> Path:
    """Resolve a leaf symlink, requiring a contained regular-file target."""
    resolved = _within(root, path)
    if not resolved.is_file():
        raise PayloadTrimError(f"staged link target is not a regular file: {path}")
    return resolved


def _list_dir(root: Path, directory: Path) -> tuple[str, ...]:
    if not os.path.lexists(directory):
        return ()
    _ancestors(root, directory)
    _within(root, directory)
    if directory.is_symlink() or not directory.is_dir():
        raise PayloadTrimError(f"unexpected staged entry: {directory}")
    return tuple(sorted(entry.name for entry in os.scandir(directory)))


def _remove_file(root: Path, path: Path, removed: list[str], site: Path) -> None:
    if not os.path.lexists(path):
        return
    _ancestors(root, path)
    if path.is_symlink():
        _leaf_link_target(root, path)
        path.unlink()
    elif path.is_file():
        _within(root, path)
        path.unlink()
    else:
        raise PayloadTrimError(f"unexpected staged entry: {path}")
    removed.append(path.relative_to(site).as_posix())


def _remove_tree(root: Path, path: Path, removed: list[str], site: Path) -> None:
    if not os.path.lexists(path):
        return
    _ancestors(root, path)
    _within(root, path)
    if path.is_symlink():
        raise PayloadTrimError(f"staged directory link not allowed: {path}")
    if not path.is_dir():
        raise PayloadTrimError(f"unexpected staged entry: {path}")
    shutil.rmtree(path)
    removed.append(path.relative_to(site).as_posix())


def _unused_lib(name: str) -> bool:
    stem = name.split(".so")[0]
    if name in _LIB_EXACT:
        return True
    if stem.startswith(_LIB_PREFIXES):
        return True
    if stem in _FFMPEG_STEMS:
        return True
    # QML/Quick satellites are Qt components only; unknown vendor stems stay.
    return stem.startswith("libQt6") and ("Qml" in stem or "Quick" in stem)


def trim_staged_payloads(*, appdir: Path, python_version: str) -> TrimReport:
    """Remove unused SDK payloads under ``appdir``; fail on escape or gaps."""
    if appdir.is_symlink():
        raise PayloadTrimError(f"staged AppDir must not be a symlink: {appdir}")
    root = appdir.resolve()
    base = ("usr", "lib", f"python{python_version}", "site-packages")
    # Validate every scope before removing anything.
    site = _scope(root, *base)
    if not site.is_dir():
        raise PayloadTrimError(f"missing staged site-packages: {site}")
    pyside = _scope(root, *base, "PySide6")
    qtlib = _scope(root, *base, "PySide6", "Qt", "lib")
    plugins = _scope(root, *base, "PySide6", "Qt", "plugins")
    vkb = _scope(
        root,
        *base,
        "PySide6",
        "Qt",
        "plugins",
        "platforminputcontexts",
        "libqtvirtualkeyboardplugin.so",
    )
    eglfs = _scope(root, *base, *_EGLFS_PLATFORM_PLUGIN)
    qml = _scope(root, *base, "PySide6", "Qt", "qml")
    libexec = _scope(root, *base, "PySide6", "Qt", "libexec")
    pyside_include = _scope(root, *base, "PySide6", "include")
    shiboken_include = _scope(root, *base, "shiboken6", "include")
    archives = [_scope(root, *base, *relative.split("/")) for relative in _STATIC_ARCHIVES]
    # Prevalidate directory leaves _scope leaves unchecked before any removal.
    for _directory in (
        site,
        pyside,
        qtlib,
        plugins,
        qml,
        libexec,
        pyside_include,
        shiboken_include,
    ):
        _list_dir(root, _directory)
    removed: list[str] = []
    for name in _list_dir(root, pyside):
        if name.startswith("Qt") and (name.endswith(".abi3.so") or name.endswith(".pyi")):
            stem = name.split(".")[0]
            if stem not in RETAINED_QT_BINDINGS:
                _remove_file(root, pyside / name, removed, site)
        elif name in _TOP_TOOLS or name.startswith("libpyside6qml"):
            _remove_file(root, pyside / name, removed, site)
    for name in _list_dir(root, qtlib):
        if _unused_lib(name):
            _remove_file(root, qtlib / name, removed, site)
    for name in _list_dir(root, plugins):
        if name in _PLUGIN_DIRS:
            _remove_tree(root, plugins / name, removed, site)
    _remove_file(root, vkb, removed, site)
    _remove_file(root, eglfs, removed, site)
    _remove_tree(root, qml, removed, site)
    for name in _LIBEXEC_TOOLS:
        _remove_file(root, libexec / name, removed, site)
    _remove_tree(root, pyside_include, removed, site)
    _remove_tree(root, shiboken_include, removed, site)
    for path in archives:
        _remove_file(root, path, removed, site)
    missing = [entry for entry in _REQUIRED if not _required_present(root, site, base, entry)]
    if missing:
        raise PayloadTrimError(f"missing required staged runtime file: {missing[0]}")
    return TrimReport(tuple(sorted(removed)))


def _required_present(root: Path, site: Path, base: tuple[str, ...], entry: str) -> bool:
    if "*" in entry:
        parent = _scope(root, *base, *entry.split("/")[:-1])
        if parent.is_symlink():
            raise PayloadTrimError(f"staged directory link not allowed: {parent}")
        if not parent.is_dir():
            return False
        pattern = entry.rpartition("/")[2]
        present = False
        for match in sorted(parent.glob(pattern)):
            if match.is_symlink():
                _leaf_link_target(root, match)
                present = True
            elif match.is_file():
                present = True
        return present
    path = _scope(root, *base, *entry.split("/"))
    if not os.path.lexists(path):
        return False
    if path.is_symlink():
        _leaf_link_target(root, path)
        return True
    return path.is_file()
