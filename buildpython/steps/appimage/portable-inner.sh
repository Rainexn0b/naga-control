#!/bin/bash
# In-container phases for the controlled portable build.
# Runs only inside the pinned Ubuntu 22.04 image; never on the host.
set -euo pipefail

CONTROL_BIN="/opt/naga-python/bin/python3.12"
EXPECTED_PY="3.12.15"
EXPECTED_GLIBC="2.35"
APPDIR="/workspace/build/appimage/AppDir"
APPRUN="$APPDIR/AppRun"

usage() {
  cat <<'USAGE'
Usage: portable-inner.sh <build|gate|check> [--help]
Run one controlled phase inside the Ubuntu 22.04 builder image:
  build  assemble the existing AppImage step only
  gate   static finished-artifact ABI gate with --baseline-root /
  check  Ubuntu 22.04 baseline userspace smoke (offscreen Qt, help, version)
The static gate runs before any bundled execution. Gate and check are
offline with no GUI, service, hardware, or device access.
USAGE
}

if [ "$#" -eq 1 ]; then
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
  esac
fi
if [ "$#" -ne 1 ]; then
  echo "portable-inner.sh: expected exactly one phase argument" >&2
  exit 2
fi
phase="$1"
case "$phase" in
  build|gate|check) ;;
  *)
    echo "portable-inner.sh: unknown phase: $phase" >&2
    exit 2
    ;;
esac

require_nonroot() {
  if [ "$(id -u)" -eq 0 ]; then
    echo "portable-inner.sh: refusing to run $phase as root" >&2
    exit 1
  fi
}

require_toolchain() {
  test "$(uname -m)" = "x86_64"
  "$CONTROL_BIN" --version | grep -q "$EXPECTED_PY"
  getconf GNU_LIBC_VERSION | grep -q "$EXPECTED_GLIBC"
}

require_clean_python_env() {
  if [ "${PYTHON_BIN:-}" != "$CONTROL_BIN" ]; then
    echo "portable-inner.sh: PYTHON_BIN must be $CONTROL_BIN" >&2
    exit 1
  fi
  if [ -n "${PYTHONHOME:-}" ]; then
    echo "portable-inner.sh: PYTHONHOME must be empty" >&2
    exit 1
  fi
  if [ -n "${PYTHONPATH:-}" ]; then
    echo "portable-inner.sh: PYTHONPATH must be empty" >&2
    exit 1
  fi
  if [ -n "${LD_PRELOAD:-}" ]; then
    echo "portable-inner.sh: LD_PRELOAD must be empty" >&2
    exit 1
  fi
  if [ -n "${VIRTUAL_ENV:-}" ]; then
    echo "portable-inner.sh: VIRTUAL_ENV must not leak into the controlled phases" >&2
    exit 1
  fi
  if [ -e "/workspace/.venv/bin/python" ]; then
    case ":$PATH:" in
      *"/workspace/.venv"*)
        echo "portable-inner.sh: host .venv must not be on PATH" >&2
        exit 1
        ;;
    esac
  fi
}

one_appimage() {
  shopt -s nullglob
  images=(/workspace/dist/Naga-Control-*-x86_64.AppImage)
  if [ "${#images[@]}" -ne 1 ]; then
    echo "portable-inner.sh: expected exactly one AppImage, found ${#images[@]}" >&2
    exit 1
  fi
  printf '%s' "${images[0]}"
}

phase_build() {
  require_nonroot
  require_toolchain
  require_clean_python_env
  "$CONTROL_BIN" -c "import ssl, zlib, math, cmath, bz2, lzma, ctypes, sqlite3, uuid; print(\"stdlib-probe-ok\")"
  export HOME=/tmp/opencode/home
  mkdir -p "$HOME" /tmp/opencode
  env -u PYTHONHOME -u PYTHONPATH -u LD_PRELOAD LD_LIBRARY_PATH=/opt/naga-python/lib "$CONTROL_BIN" -m venv /tmp/opencode/portable-venv
  /tmp/opencode/portable-venv/bin/pip install -e ".[dev]"
  /tmp/opencode/portable-venv/bin/python -m buildpython --run-steps AppImage
  image="$(one_appimage)"
  test -s "$image"
  printf '%s\n' "portable build complete; static gate pending"
}

phase_gate() {
  require_nonroot
  require_toolchain
  require_clean_python_env
  if [ ! -f "/usr/bin/unsquashfs" ]; then
    echo "portable-inner.sh: missing /usr/bin/unsquashfs" >&2
    exit 1
  fi
  if [ ! -f "/usr/bin/readelf" ]; then
    echo "portable-inner.sh: missing /usr/bin/readelf" >&2
    exit 1
  fi
  if [ ! -d "/" ]; then
    echo "portable-inner.sh: baseline root / is unavailable" >&2
    exit 1
  fi
  image="$(one_appimage)"
  test -s "$image"
  env -u PYTHONHOME -u PYTHONPATH -u LD_PRELOAD LD_LIBRARY_PATH=/opt/naga-python/lib PYTHON_BIN="$CONTROL_BIN" "$CONTROL_BIN" -m buildpython.steps.appimage.artifact "$image" --baseline-root /
  printf '%s\n' "static gate pass; baseline userspace check pending"
}

expected_version() {
  "$CONTROL_BIN" -c "import tomllib; print(tomllib.load(open('/workspace/pyproject.toml','rb'))['project']['version'])"
}

phase_check() {
  require_nonroot
  require_clean_python_env
  if [ "${QT_QPA_PLATFORM:-}" != "offscreen" ]; then
    echo "portable-inner.sh: QT_QPA_PLATFORM must be offscreen" >&2
    exit 1
  fi
  if [ ! -x "$APPRUN" ]; then
    echo "portable-inner.sh: missing executable $APPRUN (run build first)" >&2
    exit 1
  fi
  if [ ! -f "$APPDIR/usr/bin/python3" ]; then
    echo "portable-inner.sh: missing bundled $APPDIR/usr/bin/python3" >&2
    exit 1
  fi
  export HOME=/tmp/opencode/home
  mkdir -p "$HOME" /tmp/opencode
  expected="$(expected_version)"
  if [ -n "${RELEASE_VERSION:-}" ] && [ "$expected" != "$RELEASE_VERSION" ]; then
    echo "portable-inner.sh: pyproject version $expected != RELEASE_VERSION $RELEASE_VERSION" >&2
    exit 1
  fi
  bundled="$(APPDIR="$APPDIR" QT_QPA_PLATFORM=offscreen HOME="$HOME" "$APPRUN" python -c "from importlib.metadata import version; print(version('naga-control'))")"
  if [ "$bundled" != "$expected" ]; then
    echo "portable-inner.sh: bundled version $bundled != expected version $expected" >&2
    exit 1
  fi
  printf '%s\n' "bundled version: $bundled"
  APPDIR="$APPDIR" QT_QPA_PLATFORM=offscreen HOME="$HOME" "$APPRUN" python -c "import dbus, dbus_next, evdev, pyudev, tomli_w, packaging, numpy; from importlib.metadata import version; assert version('naga-control') == '$expected'; print('runtime-imports-ok')"
  APPDIR="$APPDIR" QT_QPA_PLATFORM=offscreen HOME="$HOME" "$APPRUN" python -c "from PySide6.QtWidgets import QApplication; from naga_control.gui.app import main; app = QApplication([]); print('qt-offscreen-ok')"
  APPDIR="$APPDIR" QT_QPA_PLATFORM=offscreen HOME="$HOME" "$APPRUN" service --help >/dev/null
  APPDIR="$APPDIR" QT_QPA_PLATFORM=offscreen HOME="$HOME" "$APPRUN" capture --help >/dev/null
  APPDIR="$APPDIR" QT_QPA_PLATFORM=offscreen HOME="$HOME" "$APPRUN" integration --help >/dev/null
  APPDIR="$APPDIR" QT_QPA_PLATFORM=offscreen HOME="$HOME" "$APPRUN" python -c "from pathlib import Path; from tempfile import TemporaryDirectory; from naga_control.integration_cli import default_source_dir, install; from contextlib import ExitStack; stack = ExitStack(); temporary = Path(stack.enter_context(TemporaryDirectory())); installed = install(default_source_dir(), home=temporary / 'home', udev_dir=temporary / 'udev', exec_prefix=Path('/test/naga.AppImage')); assert len(installed) == 8; assert 'KillMode=mixed' in (temporary / 'home/.config/systemd/user/naga-control.service').read_text(); stack.close(); print('integration-payload-ok')"
  printf '%s\n' "baseline userspace smoke pass (desktop/hardware acceptance still required)"
}

case "$phase" in
  build) phase_build ;;
  gate) phase_gate ;;
  check) phase_check ;;
esac
