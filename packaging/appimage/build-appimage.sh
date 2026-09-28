#!/usr/bin/env bash
# Build the Naga Control AppImage into dist/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="$ROOT/build/appimage"
APPDIR="$BUILD/AppDir"
PYTHON_BIN="${PYTHON_BIN:-python3}"
ARCH="${ARCH:-$(uname -m)}"

rm -rf "$BUILD"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/lib" "$APPDIR/usr/share/naga-control" "$BUILD"

echo "==> building wheel"
"$ROOT/.venv/bin/python" -m build --wheel --outdir "$BUILD" >/dev/null
WHEEL="$(ls "$BUILD"/naga_control-*.whl | head -n 1)"

echo "==> collecting runtime dependencies in a staging venv"
"$PYTHON_BIN" -m venv "$BUILD/venv"
"$BUILD/venv/bin/pip" install --quiet --upgrade pip
"$BUILD/venv/bin/pip" install --quiet "$WHEEL"
"$BUILD/venv/bin/pip" install --quiet dbus-python

PYVER="$("$BUILD/venv/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
SITE="$BUILD/venv/lib/python$PYVER/site-packages"
SYSTEM_STDLIB="$( "$PYTHON_BIN" -c 'import sysconfig; print(sysconfig.get_paths()["stdlib"])')"

echo "==> assembling AppDir for python $PYVER"
mkdir -p "$APPDIR/usr/lib/python$PYVER"
cp -a "$SITE" "$APPDIR/usr/lib/python$PYVER/site-packages"
cp -a "$SYSTEM_STDLIB/." "$APPDIR/usr/lib/python$PYVER/"
rm -rf "$APPDIR/usr/lib/python$PYVER/test" \
       "$APPDIR/usr/lib/python$PYVER/idlelib" \
       "$APPDIR/usr/lib/python$PYVER/tkinter" \
       "$APPDIR/usr/lib/python$PYVER/site-packages/pip" \
       "$APPDIR/usr/lib/python$PYVER/site-packages/pip-"*.dist-info \
       "$APPDIR/usr/lib/python$PYVER/site-packages/setuptools" \
       "$APPDIR/usr/lib/python$PYVER/site-packages/setuptools-"*.dist-info \
       "$APPDIR/usr/lib/python$PYVER/site-packages/_distutils_hack" \
       "$APPDIR/usr/lib/python$PYVER/site-packages/distutils-precedence.pth" \
       "$APPDIR/usr/lib/python$PYVER/site-packages/wheel" \
       "$APPDIR/usr/lib/python$PYVER/site-packages/wheel-"*.dist-info
find "$APPDIR/usr/lib" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
cp --dereference "$(command -v "$PYTHON_BIN")" "$APPDIR/usr/bin/python3"

LIBPYTHON="$(ldd "$APPDIR/usr/bin/python3" | awk '/libpython/ {print $3}' | head -n 1)"
if [ -n "${LIBPYTHON:-}" ]; then
  cp --dereference "$LIBPYTHON" "$APPDIR/usr/lib/"
fi

cp -a "$ROOT/packaging" "$APPDIR/usr/share/naga-control/packaging"

echo "==> rendering icon"
QT_QPA_PLATFORM=offscreen "$ROOT/.venv/bin/python" - \
  "$ROOT/packaging/appimage/org.nagacontrol.NagaControl.svg" "$BUILD" << 'PYEOF'
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

svg, outdir = sys.argv[1], sys.argv[2]
app = QApplication(sys.argv[:1])
renderer = QSvgRenderer(svg)
for size in (128, 256):
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    image.save(f"{outdir}/icon-{size}.png")
PYEOF

cp "$BUILD/icon-128.png" "$APPDIR/.DirIcon"
cp "$BUILD/icon-256.png" "$APPDIR/org.nagacontrol.NagaControl.png"
cp "$ROOT/packaging/appimage/org.nagacontrol.NagaControl.svg" "$APPDIR/org.nagacontrol.NagaControl.svg"
cp "$ROOT/packaging/appimage/org.nagacontrol.NagaControl.desktop" "$APPDIR/"
cp "$ROOT/packaging/appimage/AppRun" "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"

echo "==> downloading appimagetool"
APPIMAGETOOL="$BUILD/appimagetool"
curl -L --fail --silent --show-error \
  -o "$APPIMAGETOOL" \
  "https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-${ARCH}.AppImage"
chmod +x "$APPIMAGETOOL"

echo "==> creating AppImage"
mkdir -p "$ROOT/dist"
VERSION="$( "$ROOT/.venv/bin/python" -c 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')"
OUTPUT="$ROOT/dist/Naga-Control-${VERSION}-${ARCH}.AppImage"
ARCH="$ARCH" "$APPIMAGETOOL" --appimage-extract-and-run "$APPDIR" "$OUTPUT"
rm -f "$BUILD/appimagetool" "$BUILD/icon-128.png" "$BUILD/icon-256.png"

echo "==> built $OUTPUT"
