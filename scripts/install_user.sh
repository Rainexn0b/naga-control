#!/usr/bin/env bash

# User installer for Naga Control (adapted from the keyRGB installer pattern):
# - Downloads the AppImage from GitHub releases
# - Installs the wrapper launcher in ~/.local/bin
# - Installs host integration (systemd user unit, D-Bus service, desktop entry)
# - Installs the udev rule with sudo

set -euo pipefail

REPO="Rainexn0b/naga-control"
ASSET_DEFAULT="Naga-Control-x86_64.AppImage"
VERSION="${NAGA_CONTROL_VERSION:-}"
BIN_DIR="$HOME/.local/bin"
APPIMAGE_DST="$BIN_DIR/naga-control.AppImage"
WRAPPER_DST="$BIN_DIR/naga-control"

die() { echo "error: $*" >&2; exit 1; }
log() { echo "==> $*"; }

[ "$(id -u)" -ne 0 ] || die "run as your desktop user, not root"
command -v curl >/dev/null || die "curl is required"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --version) VERSION="${2:-}"; shift 2 ;;
    -h|--help) echo "usage: install_user.sh [--version <tag>]"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

if [ -n "$VERSION" ]; then
  :
else
  log "resolving latest release"
  resolved="$(curl -fsSL -o /dev/null -w '%{url_effective}' "https://github.com/$REPO/releases/latest")" \
    || die "could not resolve the latest release; pass --version <tag>"
  VERSION="${resolved##*/}"
fi
DOWNLOAD_URL="https://github.com/$REPO/releases/download/$VERSION/$ASSET_DEFAULT"

mkdir -p "$BIN_DIR" "$HOME/.local/share/naga-control"
STAMP="$HOME/.local/share/naga-control/installed-tag"
INSTALLED_TAG=""
[ -f "$STAMP" ] && INSTALLED_TAG="$(cat "$STAMP" 2>/dev/null || true)"
if [ ! -f "$APPIMAGE_DST" ] || [ -n "${NAGA_CONTROL_FORCE_DOWNLOAD:-}" ] || [ "$INSTALLED_TAG" != "$VERSION" ]; then
  if [ -n "$INSTALLED_TAG" ] && [ "$INSTALLED_TAG" != "$VERSION" ]; then
    log "updating AppImage ($INSTALLED_TAG -> $VERSION)"
  else
    log "downloading AppImage for $VERSION"
  fi
  curl -fsSL -o "$APPIMAGE_DST.tmp" "$DOWNLOAD_URL" \
    || die "download failed: $DOWNLOAD_URL"
  mv "$APPIMAGE_DST.tmp" "$APPIMAGE_DST"
  chmod +x "$APPIMAGE_DST"
  printf '%s\n' "$VERSION" > "$STAMP"
else
  log "AppImage $VERSION already present; skipping download"
fi

log "installing wrapper launcher"
cat > "$WRAPPER_DST" <<EOF
#!/usr/bin/env bash
# Naga Control AppImage launcher.
exec "$APPIMAGE_DST" gui "\$@"
EOF
chmod +x "$WRAPPER_DST"

log "installing user integration (unit, D-Bus service, desktop entry)"
TMP_UDEV="$(mktemp -d)"
"$APPIMAGE_DST" --install --exec-prefix "$APPIMAGE_DST" --udev-dir "$TMP_UDEV" >/dev/null \
  || die "integration install failed"
rm -rf "$TMP_UDEV"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UDEV_SRC="$SCRIPT_DIR/../system/udev/70-naga-control.rules"
UDEV_TMP=""
if [ ! -f "$UDEV_SRC" ]; then
  # Published older tags keep the old path; both attempts stay on the same tag.
  UDEV_TMP="$(mktemp)"
  curl -fsSL -o "$UDEV_TMP" "https://raw.githubusercontent.com/$REPO/$VERSION/system/udev/70-naga-control.rules" \
    || curl -fsSL -o "$UDEV_TMP" "https://raw.githubusercontent.com/$REPO/$VERSION/packaging/udev/70-naga-control.rules" \
    || die "could not download the udev rule for $VERSION"
  UDEV_SRC="$UDEV_TMP"
fi
if command -v sudo >/dev/null; then
  log "installing udev rule (sudo)"
  sudo install -m 644 "$UDEV_SRC" /etc/udev/rules.d/70-naga-control.rules
  sudo udevadm control --reload 2>/dev/null || true
  sudo udevadm trigger 2>/dev/null || true
else
  log "sudo unavailable; copy the udev rule to /etc/udev/rules.d/ manually: $UDEV_SRC"
fi
[ -z "$UDEV_TMP" ] || rm -f "$UDEV_TMP"

log "enabling user service"
systemctl --user daemon-reload
systemctl --user enable --now naga-control.service

log "done: run '$WRAPPER_DST' (or add ~/.local/bin to PATH and run 'naga-control')"
