#!/usr/bin/env bash

# Remove only known installer-owned files, without running the installed app.

set -euo pipefail
umask 077
HOME="${HOME%/}"

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

APPIMAGE_DST="$HOME/.local/bin/naga-control.AppImage"
WRAPPER_DST="$HOME/.local/bin/naga-control"
STATE_DIR="$HOME/.local/share/naga-control"
LOCK="$STATE_DIR/install.lock"
PROFILE_DIR="$HOME/.config/naga-control"
UDEV_DST="/etc/udev/rules.d/70-naga-control.rules"
USER_FILES=(
  ".config/systemd/user/naga-control.service"
  ".local/share/dbus-1/services/org.nagacontrol.Service1.service"
  ".local/share/applications/org.nagacontrol.NagaControl.desktop"
)
for size in 64 128 256 512; do
  USER_FILES+=(".local/share/icons/hicolor/${size}x${size}/apps/org.nagacontrol.NagaControl.png")
done
BACKUP_FILES=(naga-control.AppImage installed-tag image.sha256 installer-backup)
BACKUPS=()

for tool in id systemctl flock stat dirname mkdir rm rmdir cat; do
  command -v "$tool" >/dev/null || die "$tool is required to uninstall safely (no automatic package installation)"
done
[ "$(id -u)" -ne 0 ] || die "run as your desktop user, not root"
[[ "$HOME" == /* && "$HOME" != / && "$HOME" != *//* && ! "$HOME" =~ (^|/)\.\.?(/|$) ]] \
  || die "HOME must be an absolute desktop-user directory without dot components"

# Never follow a symbolic ancestor, including ancestors above HOME. Ownership
# and non-group/other-writable directory checks apply within HOME, not /tmp etc.
no_symlinks() {
  local path="$1"
  while :; do
    [ ! -L "$path" ] || die "symlink cleanup destination/ancestor: $path"
    [ "$path" != / ] || break
    path="$(dirname "$path")" || die "could not inspect cleanup ancestor"
  done
}
safe_directory() {
  local mode
  [ -d "$1" ] && [ -O "$1" ] && [ -w "$1" ] && [ -x "$1" ] \
    || die "cleanup directory must be writable and belong to the desktop user: $1"
  mode="$(stat -Lc '%a' "$1")" || die "could not inspect directory permissions: $1"
  if ! { [[ "$mode" =~ ^[0-7]{3,4}$ ]] && (( (8#$mode & 0022) == 0 )); }; then
    die "cleanup directory must not be group/other writable: $1; fix permissions manually"
  fi
}
safe_path() {
  local target="$1" kind="${2:-file}" path="$1"
  [[ "$target" == "$HOME/"* ]] || die "cleanup destination is outside HOME: $target"
  no_symlinks "$target"
  while :; do
    if [ -e "$path" ]; then
      if [ "$path" != "$target" ] || [ "$kind" = directory ]; then
        safe_directory "$path"
      else
        [ -f "$path" ] && [ -O "$path" ] \
          || die "cleanup target must be a regular desktop-user file: $path"
      fi
    fi
    [ "$path" != "$HOME" ] || break
    path="$(dirname "$path")" || die "could not inspect cleanup ancestor"
  done
}
# Owned GUI login-startup entry only. Resolved exactly like the GUI:
# absolute XDG_CONFIG_HOME/autostart else HOME/.config/autostart.
# Ownership is the Desktop Entry marker, never the Exec path, so a moved
# image is still recognized. Interpreter-free: bash builtins plus the
# required tools above; no Python, AppImage, or integration commands.
AUTOSTART_NAME="org.nagacontrol.NagaControl.desktop"
if [ -n "${XDG_CONFIG_HOME:-}" ]; then
  case "${XDG_CONFIG_HOME}" in
    /*)
      _XDG_TRIMMED="${XDG_CONFIG_HOME%/}"
      [ -n "$_XDG_TRIMMED" ] || die "XDG_CONFIG_HOME must be an absolute directory without dot components"
      [[ "$_XDG_TRIMMED" != / && "$_XDG_TRIMMED" != *//* && ! "$_XDG_TRIMMED" =~ (^|/)\.\.?(/|$) ]] \
        || die "XDG_CONFIG_HOME must be an absolute directory without dot components"
      CONFIG_ROOT="$_XDG_TRIMMED"
      ;;
    *)
      CONFIG_ROOT="$HOME/.config"
      ;;
  esac
else
  CONFIG_ROOT="$HOME/.config"
fi
AUTOSTART_FILE="$CONFIG_ROOT/autostart/$AUTOSTART_NAME"
trim_space() {
  local s="$1"
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  printf '%s' "$s"
}
autostart_is_owned() {
  local file="$1" line trimmed key value in_group=0 type_val="" owned_val=""
  while IFS= read -r line || [ -n "$line" ]; do
    trimmed="$(trim_space "$line")"
    [ -n "$trimmed" ] || continue
    case "$trimmed" in
      \#*) continue ;;
      \[*\])
        if [ "$trimmed" = "[Desktop Entry]" ]; then
          in_group=1
        else
          in_group=0
        fi
        continue
        ;;
    esac
    if [ "$in_group" -eq 1 ]; then
      case "$trimmed" in
        *=*)
          key="${trimmed%%=*}"
          value="${trimmed#*=}"
          key="$(trim_space "$key")"
          value="$(trim_space "$value")"
          if [ "$key" = "Type" ]; then
            type_val="$value"
          elif [ "$key" = "X-NagaControl-Owned" ]; then
            owned_val="$value"
          fi
          ;;
      esac
    fi
  done < "$file"
  [ "$type_val" = "Application" ] && [ "$owned_val" = "true" ]
}
autostart_no_symlink_ancestors_ok() {
  local path
  path="$(dirname "$1")" || return 1
  while :; do
    [ ! -L "$path" ] || return 1
    [ "$path" != / ] || break
    path="$(dirname "$path")" || return 1
  done
  return 0
}
autostart_parent_dirs_ok() {
  local dir stop path mode
  dir="$(dirname "$AUTOSTART_FILE")" || return 1
  if [[ "$AUTOSTART_FILE" == "$HOME/"* ]]; then
    stop="$HOME"
  else
    stop="$CONFIG_ROOT"
  fi
  path="$dir"
  while :; do
    if [ -e "$path" ]; then
      [ -d "$path" ] || return 1
      [ -O "$path" ] || return 1
      [ -w "$path" ] && [ -x "$path" ] || return 1
      [ ! -L "$path" ] || return 1
      mode="$(stat -Lc '%a' "$path")" || return 1
      case "$mode" in
        ''|*[!0-7]*) return 1 ;;
      esac
      if ! [[ "$mode" =~ ^[0-7]{3,4}$ ]]; then
        return 1
      fi
      if (( (8#$mode & 0022) != 0 )); then
        return 1
      fi
    fi
    if [ "$path" = "$stop" ]; then
      break
    fi
    if [ "$path" = / ]; then
      return 1
    fi
    path="$(dirname "$path")" || return 1
  done
  return 0
}
no_symlinks "$HOME"
safe_directory "$HOME"
safe_path "$STATE_DIR" directory
safe_path "$LOCK"
mkdir -p "$STATE_DIR" || die "could not create installer lock directory"
safe_directory "$STATE_DIR"
exec 9>>"$LOCK" || die "could not open installer lock"
flock -n 9 || die "another Naga installer is running; wait for it to finish"
# Keep this inode and FD for the entire cleanup; service/sudo children close FD 9.

for path in "$APPIMAGE_DST" "$WRAPPER_DST" "$STATE_DIR/installed-tag"; do safe_path "$path"; done
for path in "${USER_FILES[@]}"; do safe_path "$HOME/$path"; done
if [ "$PURGE_CONFIG" -eq 1 ]; then safe_path "$PROFILE_DIR" directory; fi
shopt -s nullglob dotglob
for backup in "$STATE_DIR"/rollback.*; do
  [ -d "$backup" ] && [ ! -L "$backup" ] || continue
  [[ "${backup##*/}" =~ ^rollback\.[a-zA-Z0-9]{6}$ ]] || continue
  [ -f "$backup/installer-backup" ] && [ ! -L "$backup/installer-backup" ] || continue
  marker="$(cat "$backup/installer-backup")" || die "could not read backup marker: $backup"
  [ "$marker" = naga-control-installer-backup-v1 ] || continue
  safe_path "$backup" directory
  for path in "${BACKUP_FILES[@]}"; do safe_path "$backup/$path"; done
  BACKUPS+=("$backup")
done
no_symlinks "$UDEV_DST"
[ ! -e "$UDEV_DST" ] || [ -f "$UDEV_DST" ] || die "udev rule is not a regular file: $UDEV_DST"

# Autostart preflight before any service change or file removal. Owned-only
# validation; foreign, symlink, directory, non-regular, or missing entries
# are preserved later without error. Owned-but-unsafe entries fail here with
# files retained and no service call.
if ! autostart_no_symlink_ancestors_ok "$AUTOSTART_FILE"; then
  die "symlink cleanup destination/ancestor: $AUTOSTART_FILE"
fi
if [ -L "$AUTOSTART_FILE" ]; then
  :
elif [ -d "$AUTOSTART_FILE" ]; then
  :
elif [ ! -e "$AUTOSTART_FILE" ]; then
  :
elif [ ! -f "$AUTOSTART_FILE" ]; then
  :
elif [ ! -r "$AUTOSTART_FILE" ]; then
  die "autostart entry is unreadable; retained without changes; fix permissions manually: $AUTOSTART_FILE"
else
  if autostart_is_owned "$AUTOSTART_FILE"; then
    [ -O "$AUTOSTART_FILE" ] || die "autostart entry is not owned by the desktop user; retained without changes: $AUTOSTART_FILE"
    autostart_parent_dirs_ok || die "autostart directory is unsafe; retained without changes; fix permissions manually: $AUTOSTART_FILE"
  fi
fi

recovery() { die "$*; files retained. Quit the GUI, stop Naga manually and verify it is inactive, then rerun uninstall (manual recovery required)"; }
active_state() { systemctl --user show naga-control.service --property=ActiveState --value 9>&-; }
ensure_stopped() {
  local state
  state="$(active_state)" || recovery "could not verify Naga service state"
  [ "$state" = inactive ] || recovery "Naga is not inactive (state: $state)"
}
systemctl --user show --property=Version --value 9>&- >/dev/null \
  || recovery "user systemd unavailable"
state="$(active_state)" || recovery "could not query Naga service state"
case "$state" in active|activating|reloading|inactive) ;; *) recovery "unknown/unsafe Naga service state: $state" ;; esac
unit_state="$(systemctl --user show naga-control.service --property=UnitFileState --value 9>&-)" \
  || recovery "could not query Naga unit enable state"
case "$unit_state" in
  enabled|enabled-runtime|disabled|static|indirect)
    log "Quit the Naga GUI and release held controls; stopping and disabling the Naga-only user service"
    systemctl --user stop naga-control.service 9>&- || recovery "Naga stop failed"
    ensure_stopped
    systemctl --user disable naga-control.service 9>&- || recovery "Naga disable failed" ;;
  "")
    load_state="$(systemctl --user show naga-control.service --property=LoadState --value 9>&-)" \
      || recovery "could not verify missing Naga unit"
    [ "$load_state" = not-found ] && [ "$state" = inactive ] \
      || recovery "unknown Naga unit state: $load_state" ;;
  *) recovery "unsafe Naga unit enable state: $unit_state" ;;
esac
ensure_stopped

remove_file() { rm -f -- "$1" || die "could not remove $1; uninstall incomplete, earlier removals are not rolled back"; }
for path in "$APPIMAGE_DST" "$WRAPPER_DST" "$STATE_DIR/installed-tag"; do remove_file "$path"; done
for path in "${USER_FILES[@]}"; do remove_file "$HOME/$path"; done
# Remove only the owned autostart entry, independent of --purge-config.
# Never the autostart directory or other apps. Missing, foreign, symlink,
# directory, or non-regular entries are preserved without following targets.
if ! autostart_no_symlink_ancestors_ok "$AUTOSTART_FILE"; then
  die "symlink cleanup destination/ancestor: $AUTOSTART_FILE; uninstall incomplete, earlier removals are not rolled back"
fi
if [ -L "$AUTOSTART_FILE" ]; then
  log "retained autostart symlink without following target: $AUTOSTART_FILE"
elif [ -d "$AUTOSTART_FILE" ]; then
  log "retained autostart directory without changes: $AUTOSTART_FILE"
elif [ ! -e "$AUTOSTART_FILE" ]; then
  :
elif [ ! -f "$AUTOSTART_FILE" ]; then
  log "retained non-regular autostart entry without changes: $AUTOSTART_FILE"
elif [ ! -r "$AUTOSTART_FILE" ]; then
  die "autostart entry is unreadable; uninstall incomplete, earlier removals are not rolled back: $AUTOSTART_FILE"
else
  if autostart_is_owned "$AUTOSTART_FILE"; then
    [ -O "$AUTOSTART_FILE" ] || die "autostart entry is not owned by the desktop user; uninstall incomplete, earlier removals are not rolled back: $AUTOSTART_FILE"
    autostart_parent_dirs_ok || die "autostart directory is unsafe; uninstall incomplete, earlier removals are not rolled back: $AUTOSTART_FILE"
    remove_file "$AUTOSTART_FILE"
    log "removed owned autostart entry: $AUTOSTART_FILE"
  else
    log "retained foreign autostart entry without changes: $AUTOSTART_FILE"
  fi
fi
for backup in "${BACKUPS[@]}"; do
  for path in "${BACKUP_FILES[@]}"; do remove_file "$backup/$path"; done
  remaining=("$backup"/*)
  if [ "${#remaining[@]}" -eq 0 ]; then
    rmdir -- "$backup" || die "could not remove empty backup $backup; uninstall incomplete"
  else
    log "retained backup directory with unrelated contents: $backup"
  fi
done
systemctl --user daemon-reload 9>&- \
  || die "user files removed but Naga user-unit reload failed; reload manually and rerun uninstall; no rollback performed"
log "removed AppImage, wrapper, and integration files"

if [ -f "$UDEV_DST" ]; then
  if confirm "Remove udev rule $UDEV_DST (requires sudo)?"; then
    command -v sudo >/dev/null || die "sudo is required for consented udev removal; user files already removed, rule retained"
    command -v udevadm >/dev/null || die "udevadm is required for consented udev removal; user files already removed, rule retained"
    sudo rm -f "$UDEV_DST" 9>&- || die "udev rule removal failed; user files already removed, no system rollback performed"
    sudo udevadm control --reload 9>&- \
      || die "udev rule removed but reload failed; permissions pending, ask your administrator to reload rules; no system rollback performed"
    log "removed udev rule and reloaded rules (existing device permissions are not verified)"
  else
    log "udev rule retained (removal declined)"
  fi
fi

if [ "$PURGE_CONFIG" -eq 1 ]; then
  rm -rf -- "$PROFILE_DIR" || die "profile removal failed; uninstall incomplete, earlier removals are not rolled back"
  log "removed ~/.config/naga-control"
fi

log "OpenRazer packages, group membership, and user daemon are retained; no dependency removal is performed"
log "uninstall complete"
