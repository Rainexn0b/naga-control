#!/usr/bin/env bash

# Remove only known installer-owned files, without running the installed app.
# NAGA_SESSION_HELPER_REQUIRED

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
MODE_FILE="$STATE_DIR/service-manager"
SESSION_HELPER_INSTALLED="$STATE_DIR/session-service.sh"
DBUS_SERVICE_FILE="$HOME/.local/share/dbus-1/services/org.nagacontrol.Service1.service"
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

for tool in id flock stat dirname mkdir rm rmdir cat; do
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
# Owned session service login-startup entry only. Distinct from the GUI entry:
# org.nagacontrol.Service.desktop with X-NagaControl-Service=true (never the
# GUI X-NagaControl-Owned marker). Resolved under the same CONFIG_ROOT as the
# GUI entry: absolute XDG_CONFIG_HOME/autostart else HOME/.config/autostart.
# Interpreter-free: bash builtins plus the required tools above.
SERVICE_AUTOSTART_NAME="org.nagacontrol.Service.desktop"
SERVICE_AUTOSTART_FILE="$CONFIG_ROOT/autostart/$SERVICE_AUTOSTART_NAME"
SYSTEMD_UNIT_FILE="$HOME/.config/systemd/user/naga-control.service"
service_autostart_is_owned() {
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
          elif [ "$key" = "X-NagaControl-Service" ]; then
            owned_val="$value"
          fi
          ;;
      esac
    fi
  done < "$file"
  [ "$type_val" = "Application" ] && [ "$owned_val" = "true" ]
}
service_autostart_no_symlink_ancestors_ok() {
  local path
  path="$(dirname "$1")" || return 1
  while :; do
    [ ! -L "$path" ] || return 1
    [ "$path" != / ] || break
    path="$(dirname "$path")" || return 1
  done
  return 0
}
service_autostart_parent_dirs_ok() {
  local dir stop path mode
  dir="$(dirname "$SERVICE_AUTOSTART_FILE")" || return 1
  if [[ "$SERVICE_AUTOSTART_FILE" == "$HOME/"* ]]; then
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
# Session D-Bus activation ownership: the managed session file carries
# Name=org.nagacontrol.Service1 plus an Exec line and no SystemdService line.
# Systemd-managed files (with SystemdService=) and foreign names are unmanaged
# here and must never be replaced with the uninstall fence.
activation_is_session_owned() {
  local file="$1" line trimmed key value in_group=0 name_val="" exec_val="" has_systemd=0
  while IFS= read -r line || [ -n "$line" ]; do
    trimmed="$(trim_space "$line")"
    [ -n "$trimmed" ] || continue
    case "$trimmed" in
      \#*) continue ;;
      \[*\])
        if [ "$trimmed" = "[D-BUS Service]" ]; then
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
          if [ "$key" = "Name" ]; then
            name_val="$value"
          elif [ "$key" = "Exec" ]; then
            exec_val="$value"
          elif [ "$key" = "SystemdService" ]; then
            has_systemd=1
          fi
          ;;
      esac
    fi
  done < "$file"
  [ "$name_val" = "org.nagacontrol.Service1" ] && [ -n "$exec_val" ] && [ "$has_systemd" -eq 0 ]
}
activation_no_symlink_ancestors_ok() {
  local path
  path="$(dirname "$1")" || return 1
  while :; do
    [ ! -L "$path" ] || return 1
    [ "$path" != / ] || break
    path="$(dirname "$path")" || return 1
  done
  return 0
}
activation_parent_dirs_ok() {
  local dir stop path mode
  dir="$(dirname "$DBUS_SERVICE_FILE")" || return 1
  if [[ "$DBUS_SERVICE_FILE" == "$HOME/"* ]]; then
    stop="$HOME"
  else
    return 1
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
# Canonical private service-manager file: exact bytes "systemd\n" or
# "session\n". Missing means legacy systemd. Malformed, oversize, NUL,
# unreadable, symlink, non-regular, or unsafe ancestors fail closed.
# Ancestors are validated before any probe with no directory creation, so an
# unsafe or unreadable ancestor never falls back to legacy. Content is read
# with a bounded NUL-delimited read preserving the trailing newline; a NUL
# byte or >=9 bytes without EOF rejects (Bash strips NUL in command
# substitution, so size+cat alone would accept session\0/systemd\0).
read_service_manager() {
  local content="" path="" mode=""
  path="$MODE_FILE"
  while :; do
    if [ -L "$path" ]; then
      die "symlink cleanup destination/ancestor: $MODE_FILE (service manager misconfigured); retained without changes"
    fi
    if [ "$path" = "$HOME" ] || [ "$path" = / ]; then
      break
    fi
    if [ -e "$path" ] && [ "$path" != "$MODE_FILE" ]; then
      if [ ! -d "$path" ]; then
        die "service manager is misconfigured; retained without changes; fix $MODE_FILE manually"
      fi
      [ -O "$path" ] \
        || die "service manager is misconfigured; retained without changes; fix $MODE_FILE manually"
      [ -w "$path" ] && [ -x "$path" ] \
        || die "service manager is misconfigured; retained without changes; fix $MODE_FILE manually"
      mode="$(stat -Lc '%a' "$path")" \
        || die "service manager is unreadable; retained without changes; fix permissions manually: $MODE_FILE"
      case "$mode" in
        ''|*[!0-7]*) die "service manager is misconfigured; retained without changes; fix $MODE_FILE manually" ;;
      esac
      if ! [[ "$mode" =~ ^[0-7]{3,4}$ ]]; then
        die "service manager is misconfigured; retained without changes; fix $MODE_FILE manually"
      fi
      if (( (8#$mode & 0022) != 0 )); then
        die "service manager is misconfigured; retained without changes; fix $MODE_FILE manually"
      fi
      if [ ! -r "$path" ]; then
        die "service manager is unreadable; retained without changes; fix permissions manually: $MODE_FILE"
      fi
    fi
    path="$(dirname "$path")" || die "service manager is unreadable; retained without changes; fix permissions manually: $MODE_FILE"
  done
  if [ -L "$MODE_FILE" ]; then
    die "symlink cleanup destination/ancestor: $MODE_FILE (service manager misconfigured); retained without changes"
  fi
  if [ ! -e "$MODE_FILE" ]; then
    printf '%s' "systemd"
    return 0
  fi
  if [ ! -f "$MODE_FILE" ]; then
    die "service manager is misconfigured; retained without changes; fix $MODE_FILE manually"
  fi
  if [ ! -r "$MODE_FILE" ]; then
    die "service manager is unreadable; retained without changes; fix permissions manually: $MODE_FILE"
  fi
  [ -O "$MODE_FILE" ] \
    || die "service manager is not owned by the desktop user; retained without changes: $MODE_FILE"
  content=""
  if IFS= read -r -d '' -n 9 content < "$MODE_FILE"; then
    die "service manager is misconfigured; retained without changes; fix $MODE_FILE manually"
  fi
  if [ "$content" = $'systemd\n' ]; then
    printf '%s' "systemd"
    return 0
  fi
  if [ "$content" = $'session\n' ]; then
    printf '%s' "session"
    return 0
  fi
  die "service manager is misconfigured; retained without changes; fix $MODE_FILE manually"
}
# Trusted sibling session helper: checkout or bootstrapped copy next to this
# inner script. Never the installed app, wrapper, Python, or installed helper.
find_trusted_session_helper() {
  local base inner_dir candidate
  base="${BASH_SOURCE[0]:-$0}"
  inner_dir="$(cd "$(dirname "$base")" && pwd)" \
    || die "could not locate trusted session helper; retained without changes"
  candidate="$inner_dir/session_service.sh"
  if [ -L "$candidate" ]; then
    die "trusted session helper is unavailable; retained without changes"
  fi
  if [ ! -f "$candidate" ]; then
    die "trusted session helper is missing; retained without changes"
  fi
  if [ ! -r "$candidate" ]; then
    die "trusted session helper is unavailable; retained without changes"
  fi
  [ -s "$candidate" ] || die "trusted session helper is unavailable; retained without changes"
  printf '%s' "$candidate"
}
no_symlinks "$HOME"
safe_directory "$HOME"
# Read the canonical mode before creating the lock directory so a missing
# required tool fails without creating installer state. Missing means legacy
# systemd; malformed/symlink/non-regular/unreadable fails closed here.
MODE="$(read_service_manager)" || die "service manager is misconfigured; retained without changes"
if [ "$MODE" = "session" ]; then
  for tool in dbus-send sleep mv mktemp; do
    command -v "$tool" >/dev/null || die "$tool is required to uninstall safely (no automatic package installation)"
  done
else
  command -v systemctl >/dev/null || die "systemctl is required to uninstall safely (no automatic package installation)"
fi
safe_path "$STATE_DIR" directory
safe_path "$LOCK"
mkdir -p "$STATE_DIR" || die "could not create installer lock directory"
safe_directory "$STATE_DIR"
exec 9>>"$LOCK" || die "could not open installer lock"
flock -n 9 || die "another Naga installer is running; wait for it to finish"
# Authority revalidation under lock: a cooperating install can change the
# canonical manager while this operation waited in preflight. The early read
# stays for read-only tool preflight compatibility; the locked value wins and
# any change fails closed before fence, service changes, or deletions.
PRELOCK_MODE="$MODE"
LOCK_NOW_MODE="$(read_service_manager)" || die "service manager is misconfigured; retained without changes"
if [ "$LOCK_NOW_MODE" != "$PRELOCK_MODE" ]; then
  MODE="$PRELOCK_MODE"
  die "service manager changed while waiting for the installer lock (was '$PRELOCK_MODE' now '$LOCK_NOW_MODE'); rerun uninstall; files retained without changes"
fi
MODE="$PRELOCK_MODE"
# Keep this inode and FD for the entire cleanup; service/sudo/dbus children close FD 9.

for path in "$APPIMAGE_DST" "$WRAPPER_DST" "$STATE_DIR/installed-tag"; do safe_path "$path"; done
for path in "${USER_FILES[@]}"; do safe_path "$HOME/$path"; done
# The installer persists the manager marker in both modes; validate it in
# both modes and remove it only after a safe stop. Legacy absent still works.
safe_path "$MODE_FILE"
if [ "$MODE" = "session" ]; then
  safe_path "$SESSION_HELPER_INSTALLED"
fi
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

# Service autostart preflight (session only) before any service change.
# Same own-only policy as the GUI entry: foreign, symlink, directory,
# non-regular, or missing entries are preserved later without error.
# Owned-but-unsafe entries fail here with files retained and no bus call.
if [ "$MODE" = "session" ]; then
  # Session never installs the systemd user unit. An existing unit with
  # session metadata is a cross-manager leftover: fail closed for manual
  # migration instead of silently deleting an unexpected unit.
  if [ -e "$SYSTEMD_UNIT_FILE" ] || [ -L "$SYSTEMD_UNIT_FILE" ]; then
    die "unexpected systemd unit with session mode; retained without changes; remove it manually or migrate managers first: $SYSTEMD_UNIT_FILE"
  fi
  if ! service_autostart_no_symlink_ancestors_ok "$SERVICE_AUTOSTART_FILE"; then
    die "symlink cleanup destination/ancestor: $SERVICE_AUTOSTART_FILE"
  fi
  if [ -L "$SERVICE_AUTOSTART_FILE" ]; then
    :
  elif [ -d "$SERVICE_AUTOSTART_FILE" ]; then
    :
  elif [ ! -e "$SERVICE_AUTOSTART_FILE" ]; then
    :
  elif [ ! -f "$SERVICE_AUTOSTART_FILE" ]; then
    :
  elif [ ! -r "$SERVICE_AUTOSTART_FILE" ]; then
    die "service autostart entry is unreadable; retained without changes; fix permissions manually: $SERVICE_AUTOSTART_FILE"
  else
    if service_autostart_is_owned "$SERVICE_AUTOSTART_FILE"; then
      [ -O "$SERVICE_AUTOSTART_FILE" ] || die "service autostart entry is not owned by the desktop user; retained without changes: $SERVICE_AUTOSTART_FILE"
      service_autostart_parent_dirs_ok || die "service autostart directory is unsafe; retained without changes; fix permissions manually: $SERVICE_AUTOSTART_FILE"
    fi
  fi
  # Activation preflight before any fence or bus call. Missing means no
  # fence is needed. Any symlink, directory, non-regular, unreadable,
  # unowned, unsafe, foreign, or systemd-managed content fails here with
  # files retained and no bus call; never replace unmanaged content.
  if ! activation_no_symlink_ancestors_ok "$DBUS_SERVICE_FILE"; then
    die "symlink cleanup destination/ancestor: $DBUS_SERVICE_FILE"
  fi
  if [ -L "$DBUS_SERVICE_FILE" ]; then
    die "D-Bus activation entry is a symlink; retained without changes; fix manually: $DBUS_SERVICE_FILE"
  elif [ -d "$DBUS_SERVICE_FILE" ]; then
    die "D-Bus activation entry is a directory; retained without changes; fix manually: $DBUS_SERVICE_FILE"
  elif [ ! -e "$DBUS_SERVICE_FILE" ]; then
    :
  elif [ ! -f "$DBUS_SERVICE_FILE" ]; then
    die "D-Bus activation entry is not a regular file; retained without changes; fix manually: $DBUS_SERVICE_FILE"
  elif [ ! -r "$DBUS_SERVICE_FILE" ]; then
    die "D-Bus activation entry is unreadable; retained without changes; fix permissions manually: $DBUS_SERVICE_FILE"
  else
    if ! activation_is_session_owned "$DBUS_SERVICE_FILE"; then
      die "D-Bus activation entry is foreign or unmanaged; retained without changes; fix manually: $DBUS_SERVICE_FILE"
    fi
    [ -O "$DBUS_SERVICE_FILE" ] || die "D-Bus activation entry is not owned by the desktop user; retained without changes: $DBUS_SERVICE_FILE"
    activation_parent_dirs_ok || die "D-Bus activation directory is unsafe; retained without changes; fix permissions manually: $DBUS_SERVICE_FILE"
  fi
fi

recovery() { die "$*; files retained. Quit the GUI, stop Naga manually and verify it is inactive, then rerun uninstall (manual recovery required)"; }
log_retained_backups() {
  if [ -n "${ACTIVATION_BACKUP:-}" ] && [ -f "${ACTIVATION_BACKUP:-}" ] && [ ! -L "${ACTIVATION_BACKUP:-}" ]; then
    echo "recovery copy retained: ${ACTIVATION_BACKUP}" >&2
  fi
  if [ -n "${AUTOSTART_BACKUP:-}" ] && [ -f "${AUTOSTART_BACKUP:-}" ] && [ ! -L "${AUTOSTART_BACKUP:-}" ]; then
    echo "recovery copy retained: ${AUTOSTART_BACKUP}" >&2
  fi
}
session_recovery() {
  log_retained_backups
  die "$*; files retained. Quit the GUI, stop Naga manually and verify it is inactive, then rerun uninstall (manual recovery required)"
}
active_state() { systemctl --user show naga-control.service --property=ActiveState --value 9>&-; }
ensure_stopped() {
  local state
  state="$(active_state)" || recovery "could not verify Naga service state"
  [ "$state" = inactive ] || recovery "Naga is not inactive (state: $state)"
}
if [ "$MODE" = "session" ]; then
  # Managed session mode: never touch systemctl. Source only the trusted
  # sibling helper (checkout or same-ref bootstrap copy). Never execute the
  # installed app, wrapper, Python, or installed helper as control. Every
  # helper child closes FD 9; the parent keeps the installer lock.
  TRUSTED_HELPER="$(find_trusted_session_helper)" \
    || session_recovery "trusted session helper is unavailable"
  # shellcheck disable=SC1090
  source "$TRUSTED_HELPER" \
    || session_recovery "trusted session helper is unavailable"
  ACTIVATION_BACKUP=""
  AUTOSTART_BACKUP=""
  FENCE_TMP=""
  cleanup_own_fence_tmp() {
    if [ -n "${FENCE_TMP:-}" ] && [ -f "$FENCE_TMP" ] && [ ! -L "$FENCE_TMP" ]; then
      rm -f -- "$FENCE_TMP" || true
    fi
    FENCE_TMP=""
  }
  # Activation fence BEFORE any PrepareShutdown or file deletion: keep a
  # private unique recovery copy of the validated real file in STATE_DIR,
  # then atomically replace it with a direct-activation blocker using a
  # unique sibling, then synchronously reload the broker. The predictable
  # legacy name is never clobbered. Original bytes are retained on failure.
  if [ -e "$DBUS_SERVICE_FILE" ]; then
    FENCE_DIR="$(dirname "$DBUS_SERVICE_FILE")" \
      || session_recovery "could not fence D-Bus activation"
    ACTIVATION_BACKUP="$(mktemp "$STATE_DIR/.session-uninstall.activation.XXXXXX" 9>&-)" \
      || session_recovery "could not fence D-Bus activation"
    cat "$DBUS_SERVICE_FILE" > "$ACTIVATION_BACKUP" \
      || session_recovery "could not fence D-Bus activation"
    FENCE_TMP="$(mktemp "$FENCE_DIR/.naga-fence.XXXXXX" 9>&-)" \
      || session_recovery "could not fence D-Bus activation"
    if [ -L "$FENCE_TMP" ] || [ -d "$FENCE_TMP" ]; then
      cleanup_own_fence_tmp
      session_recovery "could not fence D-Bus activation"
    fi
    printf '[D-BUS Service]\nName=org.nagacontrol.Service1\nExec=/bin/false\n' > "$FENCE_TMP" \
      || { cleanup_own_fence_tmp; session_recovery "could not fence D-Bus activation"; }
    mv -fT "$FENCE_TMP" "$DBUS_SERVICE_FILE" 9>&- \
      || { cleanup_own_fence_tmp; session_recovery "could not fence D-Bus activation"; }
    FENCE_TMP=""
    naga_session_reload >/dev/null \
      || session_recovery "session bus reload failed"
  fi
  # Fence the owned XDG login entry before Prepare: a D-Bus blocker alone
  # does not stop `Exec=IMAGE service` autostart. Atomically set Hidden=true
  # with no file deletion, keeping a private unique original backup in
  # STATE_DIR retained with the activation backup on uncertain failure.
  # Foreign, symlink, directory, non-regular, or missing entries are
  # preserved as before.
  if [ -L "$SERVICE_AUTOSTART_FILE" ]; then
    log "retained service autostart symlink without following target: $SERVICE_AUTOSTART_FILE"
  elif [ -d "$SERVICE_AUTOSTART_FILE" ]; then
    log "retained service autostart directory without changes: $SERVICE_AUTOSTART_FILE"
  elif [ ! -e "$SERVICE_AUTOSTART_FILE" ]; then
    :
  elif [ ! -f "$SERVICE_AUTOSTART_FILE" ]; then
    log "retained non-regular service autostart entry without changes: $SERVICE_AUTOSTART_FILE"
  elif [ ! -r "$SERVICE_AUTOSTART_FILE" ]; then
    session_recovery "service autostart entry is unreadable"
  else
    if service_autostart_is_owned "$SERVICE_AUTOSTART_FILE"; then
      [ -O "$SERVICE_AUTOSTART_FILE" ] \
        || session_recovery "service autostart entry is not owned by the desktop user"
      service_autostart_parent_dirs_ok \
        || session_recovery "service autostart directory is unsafe"
      AUTOSTART_BACKUP="$(mktemp "$STATE_DIR/.session-uninstall.autostart.XXXXXX" 9>&-)" \
        || session_recovery "could not fence service autostart"
      cat "$SERVICE_AUTOSTART_FILE" > "$AUTOSTART_BACKUP" \
        || session_recovery "could not fence service autostart"
      AUTOSTART_TMP="$(mktemp "$(dirname "$SERVICE_AUTOSTART_FILE")/.naga-autostart.XXXXXX" 9>&-)" \
        || session_recovery "could not fence service autostart"
      {
        hidden_done=0
        in_entry=0
        while IFS= read -r line || [ -n "$line" ]; do
          trimmed="$(trim_space "$line")"
          case "$trimmed" in
            \[*\])
              if [ "$in_entry" -eq 1 ] && [ "$hidden_done" -eq 0 ]; then
                printf 'Hidden=true\n'
                hidden_done=1
              fi
              if [ "$trimmed" = "[Desktop Entry]" ]; then
                in_entry=1
              else
                in_entry=0
              fi
              printf '%s\n' "$line"
              continue
              ;;
          esac
          if [ "$in_entry" -eq 1 ]; then
            case "$trimmed" in
              Hidden=*)
                printf 'Hidden=true\n'
                hidden_done=1
                continue
                ;;
            esac
          fi
          printf '%s\n' "$line"
        done < "$SERVICE_AUTOSTART_FILE"
        if [ "$hidden_done" -eq 0 ]; then
          printf 'Hidden=true\n'
        fi
      } > "$AUTOSTART_TMP" || { rm -f -- "$AUTOSTART_TMP"; session_recovery "could not fence service autostart"; }
      mv -fT "$AUTOSTART_TMP" "$SERVICE_AUTOSTART_FILE" 9>&- \
        || { rm -f -- "$AUTOSTART_TMP"; session_recovery "could not fence service autostart"; }
      log "fenced owned service autostart entry Hidden=true: $SERVICE_AUTOSTART_FILE"
    else
      log "retained foreign service autostart entry without changes: $SERVICE_AUTOSTART_FILE"
    fi
  fi
  # Clean stop through the trusted helper: successful PrepareShutdown ACK,
  # then Exit to the captured UNIQUE owner, verifying BOTH unique and
  # well-known name loss. Prepare failure, unknown bus, name replacement,
  # or timeout fails closed with files, blocker, Hidden fence, and private
  # backups retained and no PID signals. Missing bus is unknown, never
  # inactive. No owned file removal happens until this clean ack plus name
  # verification.
  log "Quit the Naga GUI and release held controls; stopping the Naga-only session service"
  naga_session_stop >/dev/null \
    || session_recovery "Naga session stop failed"
  SESSION_STATUS="$(naga_session_status)" \
    || session_recovery "could not verify Naga session service state"
  [ "$SESSION_STATUS" = "inactive" ] \
    || session_recovery "Naga session is not inactive"
else
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
fi

remove_file() { rm -f -- "$1" || die "could not remove $1; uninstall incomplete, earlier removals are not rolled back"; }
if [ "$MODE" = "session" ]; then
  for path in "$APPIMAGE_DST" "$WRAPPER_DST" "$STATE_DIR/installed-tag"; do remove_file "$path"; done
  # Session never installs the systemd unit (preflight fails if present);
  # remove only the session-owned integration files explicitly, never the
  # cross-manager unit.
  for rel in ".local/share/dbus-1/services/org.nagacontrol.Service1.service" ".local/share/applications/org.nagacontrol.NagaControl.desktop"; do
    remove_file "$HOME/$rel"
  done
  for size in 64 128 256 512; do
    remove_file "$HOME/.local/share/icons/hicolor/${size}x${size}/apps/org.nagacontrol.NagaControl.png"
  done
else
  for path in "$APPIMAGE_DST" "$WRAPPER_DST" "$STATE_DIR/installed-tag"; do remove_file "$path"; done
  for path in "${USER_FILES[@]}"; do remove_file "$HOME/$path"; done
  # Installer persists the marker in both modes; remove it after a safe stop
  # only when present so legacy absent still works with no extra deletion.
  if [ -e "$MODE_FILE" ] || [ -L "$MODE_FILE" ]; then
    remove_file "$MODE_FILE"
  fi
fi
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
# Session service autostart was fenced Hidden=true before Prepare with no
# deletion. This post-stop step removes the owned entry with the same
# own-only policy. Foreign, symlink, directory, non-regular, or missing
# entries are preserved without following targets.
if [ "$MODE" = "session" ]; then
  if ! service_autostart_no_symlink_ancestors_ok "$SERVICE_AUTOSTART_FILE"; then
    die "symlink cleanup destination/ancestor: $SERVICE_AUTOSTART_FILE; uninstall incomplete, earlier removals are not rolled back"
  fi
  if [ -L "$SERVICE_AUTOSTART_FILE" ]; then
    log "retained service autostart symlink without following target: $SERVICE_AUTOSTART_FILE"
  elif [ -d "$SERVICE_AUTOSTART_FILE" ]; then
    log "retained service autostart directory without changes: $SERVICE_AUTOSTART_FILE"
  elif [ ! -e "$SERVICE_AUTOSTART_FILE" ]; then
    :
  elif [ ! -f "$SERVICE_AUTOSTART_FILE" ]; then
    log "retained non-regular service autostart entry without changes: $SERVICE_AUTOSTART_FILE"
  elif [ ! -r "$SERVICE_AUTOSTART_FILE" ]; then
    die "service autostart entry is unreadable; uninstall incomplete, earlier removals are not rolled back: $SERVICE_AUTOSTART_FILE"
  else
    if service_autostart_is_owned "$SERVICE_AUTOSTART_FILE"; then
      [ -O "$SERVICE_AUTOSTART_FILE" ] || die "service autostart entry is not owned by the desktop user; uninstall incomplete, earlier removals are not rolled back: $SERVICE_AUTOSTART_FILE"
      service_autostart_parent_dirs_ok || die "service autostart directory is unsafe; uninstall incomplete, earlier removals are not rolled back: $SERVICE_AUTOSTART_FILE"
      remove_file "$SERVICE_AUTOSTART_FILE"
      log "removed owned service autostart entry: $SERVICE_AUTOSTART_FILE"
    else
      log "retained foreign service autostart entry without changes: $SERVICE_AUTOSTART_FILE"
    fi
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
if [ "$MODE" = "session" ]; then
  # Flush the broker cache after activation+autostart removal and before
  # claiming complete. Mode/helper are retained until after this point so a
  # reload failure allows honest retry/manual recovery with no false pass.
  # Private recovery backups are retained on failure and cleaned only on
  # verified complete removal of this invocation's own files.
  if ! naga_session_reload >/dev/null; then
    log_retained_backups
    die "session bus reload failed; uninstall incomplete, earlier removals are not rolled back: $DBUS_SERVICE_FILE"
  fi
  for path in "$MODE_FILE" "$SESSION_HELPER_INSTALLED"; do remove_file "$path"; done
  if [ -n "${ACTIVATION_BACKUP:-}" ]; then
    if [ -f "$ACTIVATION_BACKUP" ] && [ ! -L "$ACTIVATION_BACKUP" ]; then
      rm -f -- "$ACTIVATION_BACKUP" || die "could not remove recovery backup $ACTIVATION_BACKUP; uninstall incomplete"
    fi
  fi
  if [ -n "${AUTOSTART_BACKUP:-}" ]; then
    if [ -f "$AUTOSTART_BACKUP" ] && [ ! -L "$AUTOSTART_BACKUP" ]; then
      rm -f -- "$AUTOSTART_BACKUP" || die "could not remove recovery backup $AUTOSTART_BACKUP; uninstall incomplete"
    fi
  fi
  log "removed AppImage, wrapper, and integration files"
else
  systemctl --user daemon-reload 9>&- \
    || die "user files removed but Naga user-unit reload failed; reload manually and rerun uninstall; no rollback performed"
  log "removed AppImage, wrapper, and integration files"
fi

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
