#!/usr/bin/env bash

# Remove a Naga Control user installation (adapted from the keyRGB pattern).

set -euo pipefail

die() { echo "error: $*" >&2; exit 1; }
log() { echo "==> $*"; }

YES=0
PURGE_CONFIG=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    -y|--yes) YES=1; shift ;;
    --purge-config) PURGE_CONFIG=1; shift ;;
    -h|--help) echo "usage: uninstall.sh [--yes] [--purge-config]"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

confirm() {
  [ "$YES" -eq 1 ] && return 0
  local reply=""
  read -r -p "$1 [y/N] " reply || reply=""
  [[ "${reply,,}" == "y" || "${reply,,}" == "yes" ]]
}

[ "$(id -u)" -ne 0 ] || die "run as your desktop user, not root"

log "stopping and disabling the user service"
systemctl --user disable --now naga-control.service 2>/dev/null || true

APPIMAGE_DST="$HOME/.local/bin/naga-control.AppImage"
WRAPPER_DST="$HOME/.local/bin/naga-control"
if [ -f "$APPIMAGE_DST" ]; then
  "$APPIMAGE_DST" --uninstall >/dev/null 2>&1 || true
else
  python3 -m naga_control.integration_cli remove >/dev/null 2>&1 || true
fi
rm -f "$APPIMAGE_DST" "$WRAPPER_DST"
# Only installer-owned rollback pairs/stamp are removed; retain the stable
# install.lock inode and never remove dependencies or user profiles here.
STATE_DIR="$HOME/.local/share/naga-control"
if [ -d "$STATE_DIR" ] && [ ! -L "$STATE_DIR" ]; then
  rm -f "$STATE_DIR/installed-tag"
  for backup in "$STATE_DIR"/rollback.*; do
    [ -d "$backup" ] && [ ! -L "$backup" ] || continue
    [[ "${backup##*/}" =~ ^rollback\.[a-zA-Z0-9]{6}$ ]] || continue
    [ -f "$backup/installer-backup" ] && [ ! -L "$backup/installer-backup" ] || continue
    [ "$(cat "$backup/installer-backup")" = naga-control-installer-backup-v1 ] || continue
    rm -f "$backup/naga-control.AppImage" "$backup/installed-tag" "$backup/image.sha256" "$backup/installer-backup"
    rmdir "$backup" 2>/dev/null || true
  done
fi
log "removed AppImage, wrapper, and integration files"

UDEV_DST="/etc/udev/rules.d/70-naga-control.rules"
if [ -f "$UDEV_DST" ] && command -v sudo >/dev/null; then
  if confirm "Remove udev rule $UDEV_DST (requires sudo)?"; then
    sudo rm -f "$UDEV_DST"
    sudo udevadm control --reload 2>/dev/null || true
    log "removed udev rule"
  fi
fi

if [ "$PURGE_CONFIG" -eq 1 ]; then
  rm -rf "$HOME/.config/naga-control" 2>/dev/null || true
  log "removed ~/.config/naga-control"
fi

log "OpenRazer packages, group membership, and user daemon are retained; no dependency removal is performed"
log "uninstall complete"
