#!/usr/bin/env bash
# Verified, serialized desktop-user AppImage installation. No hardware probes.
# NAGA_SESSION_HELPER_REQUIRED
set -euo pipefail
umask 077
HOME="${HOME%/}"

REPO="Rainexn0b/naga-control"
ASSET="Naga-Control-x86_64.AppImage"
VERSION="${NAGA_CONTROL_VERSION:-}"
BIN_DIR="$HOME/.local/bin"
APPIMAGE_DST="$BIN_DIR/naga-control.AppImage"
WRAPPER_DST="$BIN_DIR/naga-control"
STATE_DIR="$HOME/.local/share/naga-control"
STAMP="$STATE_DIR/installed-tag"
SERVICE_MANAGER_FILE="$STATE_DIR/service-manager"
SESSION_HELPER_DST="$STATE_DIR/session-service.sh"
ACTIVATION_DST="$HOME/.local/share/dbus-1/services/org.nagacontrol.Service1.service"
SERVICE_AUTOSTART_NAME="org.nagacontrol.Service.desktop"
BLOCKER_CONTENT='[D-BUS Service]
Name=org.nagacontrol.Service1
Exec=/bin/false
'
INSTALL_OPENRAZER=0
OPENRAZER_HARD_SKIP=0
OPENRAZER_EXPLICIT=0
OFFER_ID="UNKNOWN"
OFFER_LIKE=""
OFFER_OS_STATUS="unknown"
OFFER_INVENTORY="unknown"
OFFER_PYTHON="unknown"
OFFER_STATUS="unknown"
OFFER_NATIVE_FAMILY=""
OFFER_NATIVE_INVENTORY="unknown"
NATIVE_GATE="unknown"
OPENRAZER_HELPER_KIND=""
OPENRAZER_INSTALLER=""
NATIVE_CODE_REF=""
EFFECTIVE_BOOTSTRAP_REF=""
HELPER_BASE_ARGS=()
RESTART_SERVICE=0
SERVICE_MANAGER_REQ="auto"
SERVICE_MANAGER=""
PRIOR_MODE=""
CONFIG_ROOT=""
SESSION_WAS_ACTIVE=0
SESSION_FENCED=0
SESSION_AUTOSTART_LIVE=""
STAGE_CONFIG=""
UDEV_PENDING=0
RECOVERY_DIR=""
RECOVERY_PENDING=""
STAGE=""
SIBLINGS=()
TOUCHED=0
COMMITTED=0
DEPENDENCIES_STARTED=0
WAS_ACTIVE=0
STOPPED=0
UNIT_TOUCHED=0
PREVIOUS_UNIT_STATE=""
BACKUP=""
BACKUP_PENDING=""
OLD_VERIFIED=0
OLD_DIGEST=""
OLD_OBSERVED=""
HAD_PREVIOUS_IMAGE=0
QUARANTINE=""
QUARANTINE_PENDING=""

die() { echo "error: $*" >&2; exit 1; }
log() { echo "==> $*"; }
while [ "$#" -gt 0 ]; do
  case "$1" in
    --version) [ "$#" -ge 2 ] || die "--version requires a tag"; VERSION="$2"; shift 2 ;;
    --install-openrazer) INSTALL_OPENRAZER=1; shift ;;
    --restart-service) RESTART_SERVICE=1; shift ;;
    --service-manager)
      [ "$#" -ge 2 ] || die "--service-manager requires auto|systemd|session"
      SERVICE_MANAGER_REQ="$2"; shift 2 ;;
    -h|--help)
      echo "usage: install_user.sh [--version <tag>] [--install-openrazer] [--restart-service] [--service-manager auto|systemd|session]"
      echo "App-only by default; offers consented OpenRazer setup if absent on eligible Arch or named Ubuntu/Debian, Fedora, openSUSE Leap/Tumbleweed, existing/manual/unknown unchanged; env =1 opts in, =0 hard skips OpenRazer."
      echo "--install-openrazer requests explicit first-install setup (reviewed reinstall/partial inventory only on Arch; existing, partial, manual, or unknown native backends need manual matching-cohort migration) and nonTTY handling."
      echo "--restart-service consents to a graceful Naga-only stop/resume; quit the GUI and release controls first."
      echo "--service-manager auto prefers a usable user systemd manager, else session when a live session D-Bus is reachable; persisted mode wins auto; explicit mismatch is refused."
      exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
case "$SERVICE_MANAGER_REQ" in
  auto|systemd|session) ;;
  *) die "--service-manager must be auto, systemd, or session" ;;
esac
case "${NAGA_CONTROL_INSTALL_OPENRAZER-}" in
  0) INSTALL_OPENRAZER=0; OPENRAZER_HARD_SKIP=1; log "NAGA_CONTROL_INSTALL_OPENRAZER=0: hard skip (including --install-openrazer)" ;;
  1) INSTALL_OPENRAZER=1 ;;
  "") [ "${NAGA_CONTROL_INSTALL_OPENRAZER+x}" != x ] || die "NAGA_CONTROL_INSTALL_OPENRAZER must be 0, 1, or unset" ;;
  *) die "NAGA_CONTROL_INSTALL_OPENRAZER must be 0, 1, or unset" ;;
esac
if [ "$INSTALL_OPENRAZER" -eq 1 ]; then OPENRAZER_EXPLICIT=1; fi
[ -z "$VERSION" ] || [[ "$VERSION" =~ ^[a-zA-Z0-9][a-zA-Z0-9._+-]*$ ]] || die "invalid release tag"
case "${APPIMAGE_EXTRACT_AND_RUN-}" in
  0) ;;
  "") [ "${APPIMAGE_EXTRACT_AND_RUN+x}" != x ] || die "unset APPIMAGE_EXTRACT_AND_RUN; managed service/desktop installation requires normal FUSE2/runtime support; extraction is manual launch-only" ;;
  *) die "unset APPIMAGE_EXTRACT_AND_RUN; managed service/desktop installation requires normal FUSE2/runtime support; extraction is manual launch-only" ;;
esac

# Reject symlink destinations/ancestors, and check existing writable ancestors
# without creating integration directories. The private lock directory is the
# sole persistent preflight exception; its inode is never unlinked by installers.
safe_path() {
  local path="$1"
  while :; do
    [ ! -L "$path" ] || die "symlink installation destination/ancestor: $path"
    if [ -e "$path" ]; then
      [ -w "$path" ] || die "destination is not writable: $path (fix ownership as your desktop user)"
      if [ "$path" != "$1" ] || [ -d "$path" ]; then
        [ -d "$path" ] && [ -x "$path" ] || die "not a usable directory: $path"
      else
        [ -f "$path" ] || die "not a regular file destination: $path"
      fi
    fi
    [ "$path" != "$HOME" ] || break
    [ "$path" != / ] || die "installation destination is outside HOME"
    path="$(dirname "$path")"
  done
}
safe_file() {
  safe_path "$1"
  [ ! -e "$1" ] || [ -f "$1" ] || die "not a regular file destination: $1"
}
# Session service-manager selection (installer/integration only; no core flag).
# Persisted mode wins auto; legacy missing marker means systemd; explicit
# mismatch is refused with manual-migration guidance. Fresh auto prefers an
# actually usable user systemd manager, else session when reachable.
trim_space() {
  local s="$1"
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  printf '%s' "$s"
}
resolve_config_root() {
  local trimmed=""
  if [ -n "${XDG_CONFIG_HOME:-}" ]; then
    case "$XDG_CONFIG_HOME" in
      /*)
        trimmed="${XDG_CONFIG_HOME%/}"
        [ -n "$trimmed" ] || die "XDG_CONFIG_HOME must be an absolute directory without dot components"
        [[ "$trimmed" != / && "$trimmed" != *//* && ! "$trimmed" =~ (^|/)\.\.?(/|$) ]] \
          || die "XDG_CONFIG_HOME must be an absolute directory without dot components"
        CONFIG_ROOT="$trimmed"
        ;;
      *)
        CONFIG_ROOT="$HOME/.config"
        ;;
    esac
  else
    CONFIG_ROOT="$HOME/.config"
  fi
}
session_autostart_live_path() {
  printf '%s' "$CONFIG_ROOT/autostart/$SERVICE_AUTOSTART_NAME"
}
prior_mode_detect() {
  local content="" path="" mode=""
  PRIOR_MODE=""
  path="$SERVICE_MANAGER_FILE"
  while :; do
    if [ -L "$path" ]; then
      die "service manager is misconfigured (symlink marker); resolve it manually before installation"
    fi
    if [ "$path" = "$HOME" ] || [ "$path" = / ]; then
      break
    fi
    if [ -e "$path" ] && [ "$path" != "$SERVICE_MANAGER_FILE" ]; then
      if [ ! -d "$path" ]; then
        die "service manager is misconfigured; resolve it manually before installation"
      fi
      [ -O "$path" ] || die "service manager is misconfigured; resolve it manually before installation"
      [ -w "$path" ] && [ -x "$path" ] || die "service manager is misconfigured; resolve it manually before installation"
      mode="$(stat -Lc '%a' "$path")" || die "service manager is misconfigured; resolve it manually before installation"
      case "$mode" in
        ''|*[!0-7]*) die "service manager is misconfigured; resolve it manually before installation" ;;
      esac
      if ! [[ "$mode" =~ ^[0-7]{3,4}$ ]]; then
        die "service manager is misconfigured; resolve it manually before installation"
      fi
      if (( (8#$mode & 0022) != 0 )); then
        die "service manager is misconfigured; resolve it manually before installation"
      fi
      if [ ! -r "$path" ]; then
        die "service manager is misconfigured; resolve it manually before installation"
      fi
    fi
    path="$(dirname "$path")" || die "service manager is misconfigured; resolve it manually before installation"
  done
  if [ -L "$SERVICE_MANAGER_FILE" ]; then
    die "service manager is misconfigured (symlink marker); resolve it manually before installation"
  fi
  if [ ! -e "$SERVICE_MANAGER_FILE" ]; then
    if [ -f "$STAMP" ] || [ -f "$APPIMAGE_DST" ] || [ -e "$HOME/.config/systemd/user/naga-control.service" ] || [ -L "$HOME/.config/systemd/user/naga-control.service" ]; then
      PRIOR_MODE="systemd"
      return 0
    fi
    PRIOR_MODE=""
    return 0
  fi
  [ -f "$SERVICE_MANAGER_FILE" ] || die "service manager is misconfigured; resolve it manually before installation"
  [ -r "$SERVICE_MANAGER_FILE" ] || die "service manager is misconfigured; resolve it manually before installation"
  [ -O "$SERVICE_MANAGER_FILE" ] || die "service manager is misconfigured; resolve it manually before installation"
  content=""
  if IFS= read -r -d '' -n 9 content < "$SERVICE_MANAGER_FILE"; then
    die "service manager is misconfigured (expected exactly 'systemd' or 'session' plus newline); resolve it manually before installation"
  fi
  if [ "$content" = $'systemd\n' ]; then
    PRIOR_MODE="systemd"
    return 0
  fi
  if [ "$content" = $'session\n' ]; then
    PRIOR_MODE="session"
    return 0
  fi
  die "service manager is misconfigured (expected exactly 'systemd' or 'session' plus newline); resolve it manually before installation"
}
session_bus_address_usable() {
  local address="${DBUS_SESSION_BUS_ADDRESS:-}"
  if [ -z "$address" ]; then
    return 1
  fi
  case "$address" in
    *autolaunch:*) return 1 ;;
  esac
  return 0
}
systemd_manager_usable() {
  local version="" active="" unit="" bus_ok=0
  command -v systemctl >/dev/null 2>&1 || return 1
  command -v busctl >/dev/null 2>&1 || return 1
  version="$(systemctl --user show --property=Version --value 2>/dev/null 9>&-)" || return 1
  [ -n "$version" ] || return 1
  busctl --user status >/dev/null 2>&1 9>&- || return 1
  active="$(systemctl --user show naga-control.service --property=ActiveState --value 2>/dev/null 9>&-)" || return 1
  case "$active" in
    active|inactive|activating|deactivating|reloading|failed) ;;
    *) return 1 ;;
  esac
  unit="$(systemctl --user show naga-control.service --property=UnitFileState --value 2>/dev/null 9>&-)" || return 1
  case "$unit" in
    ""|enabled|enabled-runtime|disabled|static|indirect|generated|transient) ;;
    *) return 1 ;;
  esac
  bus_ok=1
  [ "$bus_ok" -eq 1 ] || return 1
  return 0
}
session_bus_usable() {
  local output=""
  command -v dbus-send >/dev/null 2>&1 || return 1
  command -v sleep >/dev/null 2>&1 || return 1
  session_bus_address_usable || return 1
  output="$(dbus-send --session --print-reply --reply-timeout=10000 --dest=org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus.GetId 2>/dev/null 9>&-)" || return 1
  case "$output" in
    *'string "'*) return 0 ;;
    *) return 1 ;;
  esac
}
resolve_service_manager() {
  prior_mode_detect
  if [ "$SERVICE_MANAGER_REQ" != "auto" ]; then
    if [ -n "$PRIOR_MODE" ] && [ "$PRIOR_MODE" != "$SERVICE_MANAGER_REQ" ]; then
      die "service manager mismatch: existing install uses '$PRIOR_MODE' but '--service-manager $SERVICE_MANAGER_REQ' was requested; manual migration is required (stop/disable the incumbent, back up ~/.local/share/naga-control and integration files, uninstall, then reinstall in the new mode)"
    fi
    SERVICE_MANAGER="$SERVICE_MANAGER_REQ"
  else
    if [ -n "$PRIOR_MODE" ]; then
      SERVICE_MANAGER="$PRIOR_MODE"
    else
      if systemd_manager_usable; then
        SERVICE_MANAGER="systemd"
      elif session_bus_usable; then
        SERVICE_MANAGER="session"
      else
        die "no usable service manager: user systemd unavailable and session D-Bus unreachable; log into a normal desktop session (systemd user support or session D-Bus) before installation"
      fi
    fi
  fi
  if [ "$SERVICE_MANAGER" = "session" ]; then
    resolve_config_root
    case "$CONFIG_ROOT" in
      "$HOME"|"$HOME"/*) ;;
      *) die "XDG_CONFIG_HOME $CONFIG_ROOT is outside HOME; refusing session install rather than writing to an ignored location" ;;
    esac
  else
    CONFIG_ROOT="$HOME/.config"
  fi
  return 0
}
service_autostart_owned() {
  local file="$1" line trimmed key value in_group=0 type_val="" owned_val=""
  [ -f "$file" ] || return 1
  [ ! -L "$file" ] || return 1
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
activation_session_owned() {
  local file="$1" line trimmed key value in_group=0 name_val="" exec_val="" has_systemd=0
  [ -f "$file" ] || return 1
  [ ! -L "$file" ] || return 1
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
# Installer-local OpenRazer auto-offer detection (read-only, no execution).
# Parses os-release as data, never sources it. Unknown never means supported.
offer_parse_identity() {
  local LC_ALL=C
  local path="" data="" line="" raw="" key="" quote=""
  local seen_id=0 seen_like=0 newline=0
  OFFER_ID="UNKNOWN"
  OFFER_LIKE=""
  OFFER_OS_STATUS="unknown"
  if [ -e /etc/os-release ] || [ -L /etc/os-release ]; then
    path="/etc/os-release"
  elif [ -e /usr/lib/os-release ] || [ -L /usr/lib/os-release ]; then
    path="/usr/lib/os-release"
  else
    return 0
  fi
  [ -f "$path" ] || return 0
  [ -r "$path" ] || return 0
  if { IFS= read -r -d '' -n 65537 data < "$path"; } 2>/dev/null; then
    return 0
  fi
  OFFER_ID="UNKNOWN"
  OFFER_LIKE=""
  seen_id=0
  seen_like=0
  while [ -n "$data" ]; do
    newline=0
    if [[ "$data" == *$'\n'* ]]; then
      line="${data%%$'\n'*}"
      data="${data#*$'\n'}"
      newline=1
    else
      line="$data"
      data=""
    fi
    if [ "${#line}" -gt 4096 ]; then
      OFFER_ID="UNKNOWN"; OFFER_LIKE=""; OFFER_OS_STATUS="unknown"; return 0
    fi
    if [ "$newline" -eq 1 ]; then
      line="${line%$'\r'}"
    fi
    if [[ "$line" =~ [[:cntrl:]] ]]; then
      OFFER_ID="UNKNOWN"; OFFER_LIKE=""; OFFER_OS_STATUS="unknown"; return 0
    fi
    case "$line" in ""|\#*) continue ;; esac
    if [[ "$line" =~ ^\ *(ID|ID_LIKE)([^A-Za-z0-9_]|$) ]]; then
      [[ "$line" =~ ^(ID|ID_LIKE)= ]] || { OFFER_ID="UNKNOWN"; OFFER_LIKE=""; OFFER_OS_STATUS="unknown"; return 0; }
      key="${BASH_REMATCH[1]}"
      raw="${line#*=}"
      if [ "$key" = "ID" ]; then
        [ "$seen_id" -eq 0 ] || { OFFER_ID="UNKNOWN"; OFFER_LIKE=""; OFFER_OS_STATUS="unknown"; return 0; }
        seen_id=1
      else
        [ "$seen_like" -eq 0 ] || { OFFER_ID="UNKNOWN"; OFFER_LIKE=""; OFFER_OS_STATUS="unknown"; return 0; }
        seen_like=1
      fi
      case "$raw" in
        \"*\"|\'*\' )
          quote="${raw:0:1}"
        [ "${#raw}" -ge 2 ] || { OFFER_ID="UNKNOWN"; OFFER_LIKE=""; OFFER_OS_STATUS="unknown"; return 0; }
        [ "${raw: -1}" = "$quote" ] || { OFFER_ID="UNKNOWN"; OFFER_LIKE=""; OFFER_OS_STATUS="unknown"; return 0; }
        raw="${raw:1:${#raw}-2}"
        ;;
      esac
      if [ "$key" = "ID" ]; then
        [[ "$raw" =~ ^[a-z0-9._-]+$ ]] || { OFFER_ID="UNKNOWN"; OFFER_LIKE=""; OFFER_OS_STATUS="unknown"; return 0; }
        OFFER_ID="$raw"
      else
        [[ "$raw" =~ ^[a-z0-9._-]+(\ +[a-z0-9._-]+)*$ ]] || { OFFER_ID="UNKNOWN"; OFFER_LIKE=""; OFFER_OS_STATUS="unknown"; return 0; }
        OFFER_LIKE="$raw"
      fi
    fi
  done
  [ "$seen_id" -eq 1 ] || { OFFER_ID="UNKNOWN"; OFFER_LIKE=""; OFFER_OS_STATUS="unknown"; return 0; }
  OFFER_OS_STATUS="parsed"
}
offer_arch_eligible() {
  local rest="" token="" found_arch=0
  [ "$OFFER_OS_STATUS" = "parsed" ] || return 1
  case "$OFFER_ID" in
    arch|archlinux)
      if [ -z "$OFFER_LIKE" ]; then
        command -v pacman >/dev/null 2>&1 || return 1
        return 0
      fi
      rest="$OFFER_LIKE"
      while [ -n "$rest" ]; do
        token="${rest%% *}"
        if [[ "$rest" == *" "* ]]; then rest="${rest#* }"; else rest=""; fi
        [ -n "$token" ] || continue
        case "$token" in arch|archlinux) ;; *) return 1 ;; esac
      done
      command -v pacman >/dev/null 2>&1 || return 1
      return 0
      ;;
    ubuntu|debian|fedora|rhel|centos|rocky|almalinux|opensuse|opensuse-leap|opensuse-tumbleweed|suse|sles|alpine)
      return 1
      ;;
  esac
  [ -n "$OFFER_LIKE" ] || return 1
  rest="$OFFER_LIKE"
  while [ -n "$rest" ]; do
    token="${rest%% *}"
    if [[ "$rest" == *" "* ]]; then rest="${rest#* }"; else rest=""; fi
    [ -n "$token" ] || continue
    case "$token" in
      arch|archlinux) found_arch=1 ;;
      ubuntu|debian|fedora|rhel|centos|rocky|almalinux|opensuse|opensuse-leap|opensuse-tumbleweed|suse|sles|alpine) return 1 ;;
    esac
  done
  [ "$found_arch" -eq 1 ] || return 1
  command -v pacman >/dev/null 2>&1 || return 1
  return 0
}
offer_check_inventory() {
  local output="" line="" name="" ver="" low="" found=0
  OFFER_INVENTORY="unknown"
  command -v pacman >/dev/null 2>&1 || return 0
  [ -x "/usr/bin/python3" ] || return 0
  if ! output="$(pacman -Q 2>/dev/null | /usr/bin/python3 -I -B -c 'import sys; data=sys.stdin.buffer.read(1048577); sys.exit(1) if len(data)>1048576 or b"\x00" in data or any(b!=10 and not 32<=b<=126 for b in data) else sys.stdout.buffer.write(data)')"; then
    OFFER_INVENTORY="unknown"
    return 0
  fi
  if [ -z "$output" ]; then
    OFFER_INVENTORY="absent"
    return 0
  fi
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    if [[ "$line" =~ [[:cntrl:]] ]]; then
      OFFER_INVENTORY="unknown"
      return 0
    fi
    case "$line" in *" "* ) ;; *) OFFER_INVENTORY="unknown"; return 0 ;; esac
    name="${line%% *}"
    ver="${line#* }"
    case "$ver" in *" "* ) OFFER_INVENTORY="unknown"; return 0 ;; esac
    [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._+-]*$ ]] || { OFFER_INVENTORY="unknown"; return 0; }
    [[ "$ver" =~ ^[A-Za-z0-9][A-Za-z0-9._+:~+-]*$ ]] || { OFFER_INVENTORY="unknown"; return 0; }
    low="${name,,}"
    case "$low" in
      *openrazer*|*razer-*)
        found=1
        break
        ;;
    esac
  done <<< "$output"
  if [ "$found" -eq 1 ]; then
    OFFER_INVENTORY="present"
  else
    OFFER_INVENTORY="absent"
  fi
}
offer_check_python() {
  local LC_ALL=C
  local output=""
  OFFER_PYTHON="unknown"
  [ -x "/usr/bin/python3" ] || return 0
  if ! output="$(/usr/bin/python3 -I -B -c 'from importlib.machinery import PathFinder; p=PathFinder.find_spec("openrazer"); c=PathFinder.find_spec("openrazer.client",p.submodule_search_locations) if p else None; d=PathFinder.find_spec("openrazer_daemon"); print("OFFER-PROBE openrazer="+str(p is not None)+" client="+str(c is not None)+" daemon="+str(d is not None))' 2>/dev/null | /usr/bin/python3 -I -B -c 'import sys; data=sys.stdin.buffer.read(1048577); sys.exit(1) if len(data)>1048576 or b"\x00" in data or any(b!=10 and not 32<=b<=126 for b in data) else sys.stdout.buffer.write(data)')"; then
    OFFER_PYTHON="unknown"
    return 0
  fi
  case "$output" in
    "OFFER-PROBE openrazer=False client=False daemon=False")
      if command -v openrazer-daemon >/dev/null 2>&1; then
        OFFER_PYTHON="present"
      else
        OFFER_PYTHON="absent"
      fi
      ;;
    "OFFER-PROBE openrazer=False client=False daemon=True"|"OFFER-PROBE openrazer=False client=True daemon=False"|"OFFER-PROBE openrazer=False client=True daemon=True"|"OFFER-PROBE openrazer=True client=False daemon=False"|"OFFER-PROBE openrazer=True client=False daemon=True"|"OFFER-PROBE openrazer=True client=True daemon=False"|"OFFER-PROBE openrazer=True client=True daemon=True")
      OFFER_PYTHON="present"
      ;;
    *)
      OFFER_PYTHON="unknown"
      ;;
  esac
}
# Native family mapping uses exact named IDs only. ID_LIKE never proves
# binary or package compatibility, so derivatives stay ineligible.
offer_native_family() {
  OFFER_NATIVE_FAMILY=""
  [ "$OFFER_OS_STATUS" = "parsed" ] || return 1
  case "$OFFER_ID" in
    ubuntu|debian) OFFER_NATIVE_FAMILY="debian"; return 0 ;;
    fedora) OFFER_NATIVE_FAMILY="fedora"; return 0 ;;
    opensuse-leap|opensuse-tumbleweed) OFFER_NATIVE_FAMILY="opensuse"; return 0 ;;
    *) return 1 ;;
  esac
}
# Eligible for an automatic native offer: exact ID plus live manager and
# system Python capabilities. Read-only, no package changes.
offer_native_eligible() {
  offer_native_family || return 1
  case "$OFFER_NATIVE_FAMILY" in
    debian) command -v apt-get >/dev/null 2>&1 && command -v dpkg-query >/dev/null 2>&1 || return 1 ;;
    fedora) command -v dnf >/dev/null 2>&1 && command -v rpm >/dev/null 2>&1 || return 1 ;;
    opensuse) command -v zypper >/dev/null 2>&1 && command -v rpm >/dev/null 2>&1 || return 1 ;;
  esac
  [ -x "/usr/bin/python3" ] || return 1
  /usr/bin/python3 -I -B -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null || return 1
  return 0
}
# Confident absence only: a successful bounded full-database query with every
# row strictly parsed and unrelated. Any error or malformed row is unknown.
# A read-only byte gate (<=1MiB, NUL/non-ASCII/controls except LF reject)
# runs before Bash substitution so NUL is never silently dropped and a
# truncated tail never reads as absent.
offer_native_check_inventory() {
  local output="" line="" pkg="" ver="" low="" found=0 query_ok=0
  local status="" fields=()
  OFFER_NATIVE_INVENTORY="unknown"
  if [ "$OFFER_NATIVE_FAMILY" = "debian" ]; then
    command -v dpkg-query >/dev/null 2>&1 || return 0
    if output="$(dpkg-query -W -f='${Status} ${Package} ${Version}\n' 2>/dev/null | /usr/bin/python3 -I -B -c 'import sys; data=sys.stdin.buffer.read(1048577); sys.exit(1) if len(data)>1048576 or b"\x00" in data or any(b!=10 and not 32<=b<=126 for b in data) else sys.stdout.buffer.write(data)')"; then
      query_ok=1
      if [ -n "$output" ]; then
        while IFS= read -r line; do
          [ -n "$line" ] || continue
          if [[ "$line" =~ [[:cntrl:]] ]]; then query_ok=0; break; fi
          # shellcheck disable=SC2206
          read -r -a fields <<< "$line" || { query_ok=0; break; }
          [ "${#fields[@]}" -eq 5 ] || { query_ok=0; break; }
          status="${fields[0]} ${fields[1]} ${fields[2]}"
          pkg="${fields[3]}"
          ver="${fields[4]}"
          case "$status" in
            "install ok installed"|"install ok unpacked"|"install ok half-configured"|"install ok half-installed"|"install ok config-files"|"deinstall ok config-files"|"hold ok installed") ;;
            *) query_ok=0; break ;;
          esac
          [[ "$pkg" =~ ^[A-Za-z0-9][A-Za-z0-9._+-]*$ ]] || { query_ok=0; break; }
          [[ "$ver" =~ ^[A-Za-z0-9][A-Za-z0-9._+:~+-]*$ ]] || { query_ok=0; break; }
          low="${pkg,,}"
          case "$low" in *openrazer*|*razer-*) found=1; break ;; esac
        done <<< "$output"
      fi
    else
      query_ok=0
    fi
  else
    command -v rpm >/dev/null 2>&1 || return 0
    if output="$(rpm -qa --queryformat '%{NAME} %{VERSION}-%{RELEASE}\n' 2>/dev/null | /usr/bin/python3 -I -B -c 'import sys; data=sys.stdin.buffer.read(1048577); sys.exit(1) if len(data)>1048576 or b"\x00" in data or any(b!=10 and not 32<=b<=126 for b in data) else sys.stdout.buffer.write(data)')"; then
      query_ok=1
      if [ -n "$output" ]; then
        while IFS= read -r line; do
          [ -n "$line" ] || continue
          if [[ "$line" =~ [[:cntrl:]] ]]; then query_ok=0; break; fi
          case "$line" in *" "* ) ;; *) query_ok=0; break ;; esac
          pkg="${line%% *}"
          ver="${line#* }"
          case "$ver" in *" "* ) query_ok=0; break ;; esac
          [[ "$pkg" =~ ^[A-Za-z0-9][A-Za-z0-9._+-]*$ ]] || { query_ok=0; break; }
          [[ "$ver" =~ ^[A-Za-z0-9][A-Za-z0-9._+:~+-]*$ ]] || { query_ok=0; break; }
          low="${pkg,,}"
          case "$low" in *openrazer*|*razer-*) found=1; break ;; esac
        done <<< "$output"
      fi
    else
      query_ok=0
    fi
  fi
  if [ "$found" -eq 1 ]; then
    OFFER_NATIVE_INVENTORY="present"
  elif [ "$query_ok" -ne 1 ]; then
    OFFER_NATIVE_INVENTORY="unknown"
  else
    OFFER_NATIVE_INVENTORY="absent"
  fi
}
# Effective source code ref for native helper routing. Data only, never
# executed or used for authentication. Validated before any network.
resolve_bootstrap_ref() {
  EFFECTIVE_BOOTSTRAP_REF="${NAGA_CONTROL_BOOTSTRAP_REF:-main}"
  [[ "$EFFECTIVE_BOOTSTRAP_REF" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] || die "invalid code ref"
  case "$EFFECTIVE_BOOTSTRAP_REF" in
    *..*|/*|*/|*//*) die "invalid code ref" ;;
  esac
  if [[ "$EFFECTIVE_BOOTSTRAP_REF" =~ [[:cntrl:]] ]]; then
    die "invalid code ref"
  fi
}
# Arch-only missing-DKMS preparation. DKMS-only scope: no base-devel,
# headers, clang, or kernel upgrades. Separate default-no consent; never
# implied by --restart-service, --install-openrazer, or env=1.
ensure_arch_dkms_ready() {
  if command -v dkms >/dev/null 2>&1; then
    return 0
  fi
  log "OpenRazer driver build needs the DKMS tool, which is not installed"
  log "This separate prerequisite step would run: sudo pacman -S --needed dkms (pacman's own prompts remain; DKMS only, no base-devel/headers/clang or kernel upgrades; no hardware acceptance)"
  if [ ! -t 0 ]; then
    die "DKMS prerequisite needs a terminal for separate consent; install Arch dkms manually, then rerun the consented OpenRazer setup; Naga unchanged"
  fi
  local answer=""
  read -r -p "Install the missing DKMS prerequisite now via sudo pacman -S --needed dkms? [y/N] " answer || true
  case "$answer" in
    [yY]|[yY][eE][sS]) ;;
    *) die "DKMS prerequisite declined; install Arch dkms manually before opting in; Naga unchanged; no packages/groups/images changed" ;;
  esac
  sudo pacman -S --needed dkms 9>&- \
    || die "DKMS prerequisite install failed; possible partial package changes; Naga unchanged; inspect pacman inventory before retrying"
  hash -r 2>/dev/null || true
  command -v dkms >/dev/null 2>&1 \
    || die "DKMS still missing after the prerequisite transaction; install Arch dkms manually before opting in; Naga unchanged"
}
ensure_arch_helper() {
  OPENRAZER_INSTALLER="$SCRIPT_DIR/install_openrazer.sh"
  if [ ! -f "$OPENRAZER_INSTALLER" ]; then
    OPENRAZER_INSTALLER="$STAGE/install_openrazer.sh"
    curl -fsSL -o "$OPENRAZER_INSTALLER" "https://raw.githubusercontent.com/$REPO/$VERSION/scripts/install_openrazer.sh" \
      || die "could not download install_openrazer.sh for $VERSION"
  fi
  [ -s "$OPENRAZER_INSTALLER" ] || die "empty OpenRazer helper"
}
# Native helper comes from the source bootstrap ref, never the AppImage
# version. A checkout-local helper needs no network; otherwise resolve the
# full commit via the fixed commits API and fetch that exact raw helper.
ensure_native_helper() {
  local local_helper="$SCRIPT_DIR/install_openrazer_native.sh"
  local sha_file="" sha=""
  if [ -f "$local_helper" ] && [ ! -L "$local_helper" ] && [ -s "$local_helper" ]; then
    OPENRAZER_INSTALLER="$local_helper"
    resolve_bootstrap_ref
    NATIVE_CODE_REF="$EFFECTIVE_BOOTSTRAP_REF"
    return 0
  fi
  resolve_bootstrap_ref
  sha_file="$STAGE/naga-sha"
  curl -fsSL -H "Accept: application/vnd.github.sha" -o "$sha_file" "https://api.github.com/repos/$REPO/commits/$EFFECTIVE_BOOTSTRAP_REF" \
    || die "could not resolve Naga code ref $EFFECTIVE_BOOTSTRAP_REF; no packages built"
  [ -s "$sha_file" ] || die "invalid Naga code ref data; no packages built"
  /usr/bin/python3 -I -B - "$sha_file" <<'PY' || die "invalid Naga code ref data; no packages built"
import pathlib
import re
import sys
text = pathlib.Path(sys.argv[1]).read_text(encoding="ascii")
if not re.fullmatch(r"[0-9a-f]{40}\n?", text):
    print("error: invalid Naga code SHA", file=sys.stderr)
    sys.exit(1)
PY
  sha="$(cat "$sha_file")"
  sha="${sha%$'\n'}"
  [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || die "invalid Naga code SHA"
  OPENRAZER_INSTALLER="$STAGE/install_openrazer_native.sh"
  curl -fsSL -o "$OPENRAZER_INSTALLER" "https://raw.githubusercontent.com/$REPO/$sha/scripts/install_openrazer_native.sh" \
    || die "could not fetch native helper for $sha"
  [ -s "$OPENRAZER_INSTALLER" ] || die "empty native helper"
  NATIVE_CODE_REF="$sha"
}
USER_FILES=(
  ".local/bin/naga-control"
  ".config/systemd/user/naga-control.service"
  ".local/share/dbus-1/services/org.nagacontrol.Service1.service"
  ".local/share/applications/org.nagacontrol.NagaControl.desktop"
)
for size in 64 128 256 512; do
  USER_FILES+=(".local/share/icons/hicolor/${size}x${size}/apps/org.nagacontrol.NagaControl.png")
done
SESSION_HOME_FILES=(
  ".local/bin/naga-control"
  ".local/share/dbus-1/services/org.nagacontrol.Service1.service"
  ".local/share/applications/org.nagacontrol.NagaControl.desktop"
)
for size in 64 128 256 512; do
  SESSION_HOME_FILES+=(".local/share/icons/hicolor/${size}x${size}/apps/org.nagacontrol.NagaControl.png")
done
# Root/identity guards run before any manager probe, state write, network, or
# bus query so the original root preflight fails without side effects.
command -v id >/dev/null || die "id is required; see docs/troubleshooting.md#installer-prerequisites (no automatic package installation)"
command -v uname >/dev/null || die "uname is required; see docs/troubleshooting.md#installer-prerequisites (no automatic package installation)"
[ "$(id -u)" -ne 0 ] || die "run as your desktop user, not root"
[ -d "$HOME" ] && [ -w "$HOME" ] && [ -x "$HOME" ] || die "HOME must be an existing writable desktop-user directory"
[ "$(uname -s)" = Linux ] && [ "$(uname -m)" = x86_64 ] || die "only Linux x86_64 has this installer artifact"
safe_path "$STATE_DIR"
resolve_service_manager
SESSION_AUTOSTART_LIVE="$(session_autostart_live_path)"
log "service manager: $SERVICE_MANAGER (requested $SERVICE_MANAGER_REQ)"
if [ "$SERVICE_MANAGER" = "session" ] && [ "$INSTALL_OPENRAZER" -eq 1 ]; then
  die "session mode keeps the OpenRazer backend manual; install a matching custom module/daemon/client from source manually, then rerun without --install-openrazer (see docs/release-notes.md#required-openrazer); Naga unchanged"
fi
if [ "$SERVICE_MANAGER" = "systemd" ]; then
  for tool in id uname curl systemctl busctl sudo install udevadm sha256sum flock mktemp mkdir rm rmdir dirname cp mv chmod cmp grep stat; do
    command -v "$tool" >/dev/null || die "$tool is required; see docs/troubleshooting.md#installer-prerequisites (no automatic package installation)"
  done
else
  for tool in id uname curl dbus-send sleep sudo install udevadm sha256sum flock mktemp mkdir rm rmdir dirname cp mv chmod cmp grep stat; do
    command -v "$tool" >/dev/null || die "$tool is required; see docs/troubleshooting.md#installer-prerequisites (no automatic package installation)"
  done
fi
[ "$(id -u)" -ne 0 ] || die "run as your desktop user, not root"
[ "$(uname -s)" = Linux ] && [ "$(uname -m)" = x86_64 ] || die "only Linux x86_64 has this installer artifact"
safe_path "$STATE_DIR"
for path in "$APPIMAGE_DST" "$STAMP" "$STATE_DIR/install.lock" "$SERVICE_MANAGER_FILE" "$SESSION_HELPER_DST"; do safe_file "$path"; done
if [ "$SERVICE_MANAGER" = "systemd" ]; then
  for path in "${USER_FILES[@]}"; do safe_file "$HOME/$path"; done
else
  if [ -e "$HOME/.config/systemd/user/naga-control.service" ] || [ -L "$HOME/.config/systemd/user/naga-control.service" ]; then
    die "unexpected systemd unit with session mode; manual migration is required (stop/disable the incumbent, back up files, uninstall, then reinstall in the new mode)"
  fi
  for path in "${SESSION_HOME_FILES[@]}"; do safe_file "$HOME/$path"; done
  safe_file "$SESSION_AUTOSTART_LIVE"
  if [ -e "$SESSION_AUTOSTART_LIVE" ] || [ -L "$SESSION_AUTOSTART_LIVE" ]; then
    [ ! -L "$SESSION_AUTOSTART_LIVE" ] || die "symlink installation destination/ancestor: $SESSION_AUTOSTART_LIVE"
    [ -f "$SESSION_AUTOSTART_LIVE" ] || die "service autostart entry is not a regular file: $SESSION_AUTOSTART_LIVE; resolve it manually before installation"
    service_autostart_owned "$SESSION_AUTOSTART_LIVE" || die "foreign service autostart entry at $SESSION_AUTOSTART_LIVE; resolve it manually before installation (GUI autostart is untouched)"
  fi
  if [ -e "$ACTIVATION_DST" ] || [ -L "$ACTIVATION_DST" ]; then
    [ ! -L "$ACTIVATION_DST" ] || die "symlink installation destination/ancestor: $ACTIVATION_DST"
    [ -f "$ACTIVATION_DST" ] || die "service activation entry is not a regular file: $ACTIVATION_DST; resolve it manually before installation"
    activation_session_owned "$ACTIVATION_DST" || die "foreign service activation entry at $ACTIVATION_DST; resolve it manually before installation"
  fi
fi
if [ "$SERVICE_MANAGER" = "systemd" ]; then
  systemctl --user show --property=Version --value >/dev/null || die "user systemd unavailable; log into a normal desktop session (install systemd user support)"
  busctl --user status >/dev/null || die "session D-Bus unavailable; log into a desktop session with dbus-user-session/dbus"
else
  # Explicit session never touches systemctl/busctl; only dbus-send/sleep.
  # Persisted session with an unreachable bus fails here, not via fallback.
  if ! session_bus_usable; then
    die "session D-Bus unavailable; log into a desktop session with a live session bus before session installation"
  fi
  log "app-only install: OpenRazer packages, group, and daemon are unchanged"
  log "OpenRazer is not installed automatically in session mode; install a matching custom backend manually. Rerun without --install-openrazer. See docs/release-notes.md#required-openrazer. Installer success does not establish hardware readiness."
fi
# Desktop-user PATHs may omit the system administration directories.
ldconfig_tool="$(command -v ldconfig)" || ldconfig_tool=""
if [ ! -f "$ldconfig_tool" ] || [ ! -x "$ldconfig_tool" ]; then
  ldconfig_tool=""
  for tool in /usr/sbin/ldconfig /sbin/ldconfig; do
    if [ -f "$tool" ] && [ -x "$tool" ]; then ldconfig_tool="$tool"; break; fi
  done
fi
[ -n "$ldconfig_tool" ] || die "ldconfig is required for FUSE2 library discovery (install libc-bin/glibc)"
fuse_cache="$(LC_ALL=C "$ldconfig_tool" -p)" || die "ldconfig -p failed; cannot verify FUSE2 library availability"
fuse_library=""
while read -r library rest; do
  if [ "$library" = libfuse.so.2 ] && [[ "$rest" == *"x86-64"* && "$rest" == *"=> "* ]]; then
    candidate="${rest##*=> }"
    [ ! -r "$candidate" ] || fuse_library="$candidate"
  fi
done <<< "$fuse_cache"
# The check needs x86_64 libfuse.so.2; exact per-release package names live in the README, not here.
[ -n "$fuse_library" ] || die "FUSE2 library missing: x86_64 libfuse.so.2 not in ldconfig cache; see README install prerequisites or docs/troubleshooting.md#installer-prerequisites for exact per-release manual references"
[ "$(LC_ALL=C stat -c '%F' /dev/fuse 2>/dev/null)" = "character special file" ] && [ -r /dev/fuse ] && [ -w /dev/fuse ] \
  || die "FUSE runtime unavailable: /dev/fuse is not a usable character device; ask your administrator to enable FUSE, then log in again; no device was opened"
[ -d /sys/module/fuse ] || grep -Eq '(^|[[:space:]])fuse(blk)?$' /proc/filesystems \
  || die "kernel FUSE support unavailable; ask your administrator to enable FUSE for managed installation"

# Atomic writes always originate from unique siblings on the destination FS.
atomic_copy() {
  local source="$1" destination="$2" temporary
  mkdir -p "$(dirname "$destination")" || return 1
  temporary="$(mktemp "$(dirname "$destination")/.naga-install.XXXXXX")" || return 1
  SIBLINGS+=("$temporary")
  cp -p "$source" "$temporary" && mv -fT "$temporary" "$destination"
}
atomic_write_private() {
  local content="$1" destination="$2" mode="$3" temporary
  mkdir -p "$(dirname "$destination")" || return 1
  temporary="$(mktemp "$(dirname "$destination")/.naga-install.XXXXXX")" || return 1
  SIBLINGS+=("$temporary")
  printf '%s' "$content" > "$temporary" || return 1
  chmod "$mode" "$temporary" || return 1
  mv -fT "$temporary" "$destination"
}
ensure_session_helper() {
  local sibling="" self_dir=""
  if [ -n "${SCRIPT_DIR:-}" ] && [ -f "${SCRIPT_DIR}/session_service.sh" ]; then
    sibling="${SCRIPT_DIR}/session_service.sh"
  else
    self_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || return 1
    sibling="$self_dir/session_service.sh"
  fi
  [ -f "$sibling" ] || { echo "error: session helper is missing; refusing session operation" >&2; return 1; }
  [ ! -L "$sibling" ] || { echo "error: session helper is misconfigured" >&2; return 1; }
  # Trusted sibling from checkout or same-ref bootstrap; never the installed copy.
  # shellcheck disable=SC1090
  source "$sibling" || return 1
  command -v naga_session_bus_check >/dev/null || return 1
  command -v naga_session_status >/dev/null || return 1
  command -v naga_session_stop >/dev/null || return 1
  command -v naga_session_start >/dev/null || return 1
  command -v naga_session_reload >/dev/null || return 1
  return 0
}
systemd_active_state() { systemctl --user show naga-control.service --property=ActiveState --value 9>&-; }
session_active_state() {
  ensure_session_helper || return 1
  naga_session_status
}
active_state() {
  if [ "${SERVICE_MANAGER:-systemd}" = "session" ]; then
    session_active_state
  else
    systemd_active_state
  fi
}
ensure_stopped() {
  local state
  state="$(active_state)" || return 1
  [ "$state" = inactive ]
}
session_recovery_snapshot() {
  [ -n "${RECOVERY_DIR:-}" ] && [ -d "$RECOVERY_DIR" ] && return 0
  RECOVERY_PENDING="$(mktemp -d "$STATE_DIR/session-recovery.XXXXXX")" || return 1
  if [ -f "$ACTIVATION_DST" ] && [ ! -L "$ACTIVATION_DST" ]; then
    cp -p "$ACTIVATION_DST" "$RECOVERY_PENDING/activation.service" || return 1
  fi
  if [ -f "$SESSION_AUTOSTART_LIVE" ] && [ ! -L "$SESSION_AUTOSTART_LIVE" ]; then
    cp -p "$SESSION_AUTOSTART_LIVE" "$RECOVERY_PENDING/autostart.desktop" || return 1
  fi
  if [ -f "$SERVICE_MANAGER_FILE" ] && [ ! -L "$SERVICE_MANAGER_FILE" ]; then
    cp -p "$SERVICE_MANAGER_FILE" "$RECOVERY_PENDING/service-manager" || return 1
  fi
  if [ -f "$SESSION_HELPER_DST" ] && [ ! -L "$SESSION_HELPER_DST" ]; then
    cp -p "$SESSION_HELPER_DST" "$RECOVERY_PENDING/session-service.sh" || return 1
  fi
  chmod 700 "$RECOVERY_PENDING" || return 1
  RECOVERY_DIR="$RECOVERY_PENDING"
  RECOVERY_PENDING=""
  return 0
}
session_apply_blocker() {
  local live="$ACTIVATION_DST" parent="" blocker_tmp=""
  parent="$(dirname "$live")" || return 1
  safe_path "$parent"
  mkdir -p "$parent" || return 1
  blocker_tmp="$(mktemp "$parent/.naga-fence.XXXXXX")" || return 1
  printf '%s' "$BLOCKER_CONTENT" > "$blocker_tmp" || { rm -f -- "$blocker_tmp"; return 1; }
  chmod 644 "$blocker_tmp" || { rm -f -- "$blocker_tmp"; return 1; }
  mv -fT "$blocker_tmp" "$live" || { rm -f -- "$blocker_tmp"; return 1; }
  SESSION_FENCED=1
  return 0
}
session_hide_autostart() {
  local live="$SESSION_AUTOSTART_LIVE" parent="" hidden_tmp="" line="" trimmed=""
  local hidden_done=0 in_entry=0
  [ -f "$live" ] || return 0
  [ ! -L "$live" ] || return 1
  service_autostart_owned "$live" || return 1
  parent="$(dirname "$live")" || return 1
  safe_path "$parent"
  mkdir -p "$parent" || return 1
  hidden_tmp="$(mktemp "$parent/.naga-autostart.XXXXXX")" || return 1
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
    done < "$live"
    if [ "$hidden_done" -eq 0 ]; then
      printf 'Hidden=true\n'
    fi
  } > "$hidden_tmp" || { rm -f -- "$hidden_tmp"; return 1; }
  chmod 644 "$hidden_tmp" || { rm -f -- "$hidden_tmp"; return 1; }
  mv -fT "$hidden_tmp" "$live" || { rm -f -- "$hidden_tmp"; return 1; }
  return 0
}
session_fence_activation() {
  ensure_session_helper || return 1
  session_recovery_snapshot || return 1
  session_apply_blocker || return 1
  session_hide_autostart || return 1
  if ! naga_session_reload >/dev/null 2>&1 9>&-; then
    echo "error: session bus reload failed; activation remains fenced for manual recovery" >&2
    return 1
  fi
  return 0
}
session_reapply_fence() {
  local fence_failed=0
  ensure_session_helper 2>/dev/null || return 1
  session_apply_blocker 2>/dev/null || return 1
  session_hide_autostart 2>/dev/null || fence_failed=1
  naga_session_reload >/dev/null 2>&1 9>&- || fence_failed=1
  if [ "$fence_failed" -ne 0 ]; then
    return 1
  fi
  SESSION_FENCED=1
  return 0
}
session_is_fenced() {
  [ "${SESSION_FENCED:-0}" -eq 1 ]
}
session_restore() {
  local failed=0 path rel src_activation="" src_autostart=""
  log "installation failed: restoring previous session files (best effort)"
  ensure_session_helper || { echo "RESTORATION FAILED: session helper unavailable; files left fenced; manual recovery required" >&2; return 1; }
  session_recovery_snapshot || {
    echo "RESTORATION FAILED: recovery snapshot unavailable; files left fenced; manual recovery required" >&2
    if [ -n "${RECOVERY_DIR:-}" ]; then
      echo "operator recovery snapshot retained: $RECOVERY_DIR" >&2
    fi
    return 1
  }
  if ! session_reapply_fence; then
    echo "RESTORATION FAILED: session fence could not be re-established; files left fenced-uncertain; manual recovery required" >&2
    if [ -n "${RECOVERY_DIR:-}" ]; then
      echo "operator recovery snapshot retained: $RECOVERY_DIR" >&2
    fi
    return 1
  fi
  if [ -f "$ACTIVATION_DST" ] && [ ! -L "$ACTIVATION_DST" ]; then
    grep -qF "Exec=/bin/false" "$ACTIVATION_DST" 2>/dev/null || {
      echo "RESTORATION FAILED: activation fence unverified; files left fenced-uncertain; manual recovery required" >&2
      if [ -n "${RECOVERY_DIR:-}" ]; then
        echo "operator recovery snapshot retained: $RECOVERY_DIR" >&2
      fi
      return 1
    }
  fi
  if ! ensure_stopped; then
    if ! naga_session_stop >/dev/null 2>&1 9>&-; then
      echo "RESTORATION FAILED: session did not become inactive; files left fenced; manual recovery required" >&2
      if [ -n "${RECOVERY_DIR:-}" ]; then
        echo "operator recovery snapshot retained: $RECOVERY_DIR" >&2
      fi
      return 1
    fi
    if ! ensure_stopped; then
      echo "RESTORATION FAILED: session did not become inactive; files left fenced; manual recovery required" >&2
      if [ -n "${RECOVERY_DIR:-}" ]; then
        echo "operator recovery snapshot retained: $RECOVERY_DIR" >&2
      fi
      return 1
    fi
  fi
  for path in ".local/bin/naga-control.AppImage" ".local/share/naga-control/installed-tag" ".local/share/naga-control/service-manager" ".local/share/naga-control/session-service.sh"; do
    if [ -f "$STAGE/previous/$path" ]; then
      atomic_copy "$STAGE/previous/$path" "$HOME/$path" || failed=1
      case "$path" in
        ".local/share/naga-control/service-manager") chmod 600 "$HOME/$path" 2>/dev/null || failed=1 ;;
        ".local/share/naga-control/session-service.sh") chmod 700 "$HOME/$path" 2>/dev/null || failed=1 ;;
      esac
    else
      case "$path" in
        ".local/share/naga-control/service-manager"|".local/share/naga-control/session-service.sh")
          rm -f "$HOME/$path" 2>/dev/null || failed=1
          ;;
        ".local/bin/naga-control.AppImage"|".local/share/naga-control/installed-tag")
          rm -f "$HOME/$path" 2>/dev/null || failed=1
          ;;
      esac
    fi
  done
  if [ "$failed" -ne 0 ]; then
    if session_reapply_fence; then
      echo "RESTORATION FAILED: critical session files could not be restored; fence maintained; manual recovery required" >&2
    else
      echo "RESTORATION FAILED: critical session files could not be restored; session fence uncertain; manual recovery required" >&2
    fi
    if [ -n "${RECOVERY_DIR:-}" ]; then
      echo "operator recovery snapshot retained: $RECOVERY_DIR" >&2
    fi
    return 1
  fi
  for path in ".local/bin/naga-control" ".local/share/applications/org.nagacontrol.NagaControl.desktop" ".local/share/icons/hicolor/64x64/apps/org.nagacontrol.NagaControl.png" ".local/share/icons/hicolor/128x128/apps/org.nagacontrol.NagaControl.png" ".local/share/icons/hicolor/256x256/apps/org.nagacontrol.NagaControl.png" ".local/share/icons/hicolor/512x512/apps/org.nagacontrol.NagaControl.png"; do
    if [ -f "$STAGE/previous/$path" ]; then
      atomic_copy "$STAGE/previous/$path" "$HOME/$path" || failed=1
    else
      rm -f "$HOME/$path" 2>/dev/null || failed=1
    fi
  done
  if [ "$failed" -ne 0 ]; then
    if session_reapply_fence; then
      echo "RESTORATION FAILED: session integration could not be restored; fence maintained; manual recovery required" >&2
    else
      echo "RESTORATION FAILED: session integration could not be restored; session fence uncertain; manual recovery required" >&2
    fi
    if [ -n "${RECOVERY_DIR:-}" ]; then
      echo "operator recovery snapshot retained: $RECOVERY_DIR" >&2
    fi
    return 1
  fi
  rel="${SESSION_AUTOSTART_LIVE#"$HOME"/}"
  src_activation=""
  src_autostart=""
  if [ -f "$STAGE/previous/.local/share/dbus-1/services/org.nagacontrol.Service1.service" ]; then
    src_activation="$STAGE/previous/.local/share/dbus-1/services/org.nagacontrol.Service1.service"
  elif [ -n "${RECOVERY_DIR:-}" ] && [ -f "$RECOVERY_DIR/activation.service" ]; then
    src_activation="$RECOVERY_DIR/activation.service"
  fi
  if [ "$rel" != "$SESSION_AUTOSTART_LIVE" ] && [ -f "$STAGE/previous/$rel" ]; then
    src_autostart="$STAGE/previous/$rel"
  elif [ -n "${RECOVERY_DIR:-}" ] && [ -f "$RECOVERY_DIR/autostart.desktop" ]; then
    src_autostart="$RECOVERY_DIR/autostart.desktop"
  fi
  if [ -n "$src_activation" ]; then
    activation_session_owned "$src_activation" || failed=1
    if [ "$failed" -eq 0 ]; then
      atomic_copy "$src_activation" "$ACTIVATION_DST" || failed=1
    fi
  else
    session_apply_blocker || failed=1
  fi
  if [ -n "$src_autostart" ]; then
    service_autostart_owned "$src_autostart" || failed=1
    if [ "$failed" -eq 0 ]; then
      atomic_copy "$src_autostart" "$SESSION_AUTOSTART_LIVE" || failed=1
    fi
  else
    rm -f "$SESSION_AUTOSTART_LIVE" 2>/dev/null || failed=1
  fi
  if [ "$failed" -ne 0 ]; then
    if session_reapply_fence; then
      echo "RESTORATION FAILED: session activation could not be restored; fence maintained; manual recovery required" >&2
    else
      echo "RESTORATION FAILED: session activation could not be restored; session fence uncertain; manual recovery required" >&2
    fi
    if [ -n "${RECOVERY_DIR:-}" ]; then
      echo "operator recovery snapshot retained: $RECOVERY_DIR" >&2
    fi
    return 1
  fi
  naga_session_reload >/dev/null 2>&1 9>&- || failed=1
  if [ "$failed" -ne 0 ]; then
    if session_reapply_fence; then
      echo "RESTORATION FAILED: session reload failed; fence maintained; manual recovery required" >&2
    else
      echo "RESTORATION FAILED: session reload failed; session fence uncertain; manual recovery required" >&2
    fi
    if [ -n "${RECOVERY_DIR:-}" ]; then
      echo "operator recovery snapshot retained: $RECOVERY_DIR" >&2
    fi
    return 1
  fi
  SESSION_FENCED=0
  log "rollback restored previous files; profiles were not changed"
  if [ "$SESSION_WAS_ACTIVE" -eq 1 ]; then
    ensure_session_helper || { if session_reapply_fence; then echo "RESTORATION FAILED: previous session could not resume; fence maintained" >&2; else echo "RESTORATION FAILED: previous session could not resume; session fence uncertain" >&2; fi; if [ -n "${RECOVERY_DIR:-}" ]; then echo "operator recovery snapshot retained: $RECOVERY_DIR" >&2; fi; return 1; }
    naga_session_start >/dev/null 2>&1 9>&- || { if session_reapply_fence; then echo "RESTORATION FAILED: previous session could not resume; fence maintained" >&2; else echo "RESTORATION FAILED: previous session could not resume; session fence uncertain" >&2; fi; if [ -n "${RECOVERY_DIR:-}" ]; then echo "operator recovery snapshot retained: $RECOVERY_DIR" >&2; fi; return 1; }
    [ "$(active_state)" = "active" ] || { if session_reapply_fence; then echo "RESTORATION FAILED: previous session could not resume; fence maintained" >&2; else echo "RESTORATION FAILED: previous session could not resume; session fence uncertain" >&2; fi; if [ -n "${RECOVERY_DIR:-}" ]; then echo "operator recovery snapshot retained: $RECOVERY_DIR" >&2; fi; return 1; }
  fi
}
restore() {
  if [ "${SERVICE_MANAGER:-systemd}" = "session" ]; then
    session_restore
    return $?
  fi
  local failed=0 path
  log "installation failed: restoring previous AppImage/tag and user integration (best effort)"
  # Never restore files under a possibly running half-installed service.
  if ! ensure_stopped; then
    systemctl --user stop naga-control.service 9>&- || failed=1
    if ! ensure_stopped; then
      echo "RESTORATION FAILED: Naga did not become inactive; files left untouched; manual recovery required" >&2
      return 1
    fi
  fi
  if [ "$UNIT_TOUCHED" -eq 1 ]; then
    systemctl --user disable naga-control.service 9>&- || failed=1
  fi
  for path in ".local/bin/naga-control.AppImage" ".local/share/naga-control/installed-tag" ".local/share/naga-control/service-manager" "${USER_FILES[@]}"; do
    if [ -f "$STAGE/previous/$path" ]; then
      atomic_copy "$STAGE/previous/$path" "$HOME/$path" || failed=1
      if [ "$path" = ".local/share/naga-control/service-manager" ]; then
        chmod 600 "$HOME/$path" 2>/dev/null || failed=1
      fi
    else
      # Missing previous marker on legacy systemd means no file to restore;
      # fresh failures remove any half-written marker.
      rm -f "$HOME/$path" || failed=1
    fi
  done
  systemctl --user daemon-reload 9>&- || failed=1
  if [ "$UNIT_TOUCHED" -eq 1 ]; then
    case "$PREVIOUS_UNIT_STATE" in
      enabled) systemctl --user enable naga-control.service 9>&- || failed=1 ;;
      enabled-runtime) systemctl --user enable --runtime naga-control.service 9>&- || failed=1 ;;
    esac
  fi
  if [ "$failed" -ne 0 ]; then
    echo "RESTORATION FAILED: inspect the retained rollback pair and user integration manually" >&2
    return 1
  fi
  log "rollback restored previous files; profiles were not changed"
  # A package transaction can be partial even if its helper returned failure.
  if [ "$DEPENDENCIES_STARTED" -eq 1 ]; then
    log "Naga remains stopped: OpenRazer may have partial changes; inventory, reboot/re-login and verify before activation"
  elif [ "$WAS_ACTIVE" -eq 1 ]; then
    systemctl --user start naga-control.service 9>&- && [ "$(active_state)" = active ] \
      || { echo "RESTORATION FAILED: previous Naga service could not resume" >&2; return 1; }
  fi
}
publish_quarantine() {
  local observed=""
  [ -f "$STAGE/previous/.local/bin/naga-control.AppImage" ] || return 1
  [ -f "$STAGE/previous/.local/share/naga-control/installed-tag" ] || return 1
  observed="$(sha256sum "$STAGE/previous/.local/bin/naga-control.AppImage" 2>/dev/null || true)"
  observed="${observed:0:64}"
  QUARANTINE_PENDING="$(mktemp -d "$STATE_DIR/.quarantine.XXXXXX")" || return 1
  cp -p "$STAGE/previous/.local/bin/naga-control.AppImage" "$QUARANTINE_PENDING/naga-control.AppImage" || return 1
  cp -p "$STAGE/previous/.local/share/naga-control/installed-tag" "$QUARANTINE_PENDING/installed-tag" || return 1
  {
    printf 'naga-control-installer-quarantine-v1\n'
    printf 'UNVERIFIED previous image: not verified against release sidecar; not a rollback pair; manual recovery only\n'
    if [ -n "$observed" ]; then
      printf 'observed %s UNVERIFIED\n' "$observed"
    else
      printf 'observed unavailable UNVERIFIED\n'
    fi
    printf 'tag %s\n' "$INSTALLED_TAG"
  } > "$QUARANTINE_PENDING/quarantine" || return 1
  QUARANTINE="$STATE_DIR/quarantine.${QUARANTINE_PENDING##*.}"
  [ ! -e "$QUARANTINE" ] && [ ! -L "$QUARANTINE" ] || return 1
  mv -T "$QUARANTINE_PENDING" "$QUARANTINE" || return 1
  QUARANTINE_PENDING=""
  log "warning: unverified previous image preserved at $QUARANTINE (not a verified rollback; held until successful commit then removed; manual recovery only if install fails)"
}
# Ownership guard for post-commit retention: exact STATE_DIR child, canonical
# suffix, no symlink ancestors to /, owned/mode-checked only within HOME.
retention_owned_dir() {
  local candidate="$1" owner="$2" base path anc_uid anc_mode
  [[ "$candidate" == "$STATE_DIR"/rollback.* || "$candidate" == "$STATE_DIR"/quarantine.* ]] || return 1
  base="${candidate##*/}"
  [[ "$base" =~ ^(rollback|quarantine)\.[A-Za-z0-9]{6}$ ]] || return 1
  [[ "$owner" =~ ^[0-9]+$ ]] || return 1
  path="$candidate"
  while :; do
    [ ! -L "$path" ] || return 1
    case "$path" in
      "$HOME"/*|"$HOME")
        [ -d "$path" ] || return 1
        anc_uid="$(stat -c '%u' "$path" 2>/dev/null)" || return 1
        [ "$anc_uid" = "$owner" ] || return 1
        anc_mode="$(stat -Lc '%a' "$path" 2>/dev/null)" || return 1
        [[ "$anc_mode" =~ ^[0-7]{3,4}$ ]] || return 1
        (( (8#$anc_mode & 0022) == 0 )) || return 1
        ;;
    esac
    [ "$path" = / ] && break
    path="$(dirname "$path")" || return 1
  done
  return 0
}
# Regular owned file, never following symlinks.
retention_owned_file() {
  local path="$1" owner="$2" have_uid
  [ -f "$path" ] || return 1
  [ ! -L "$path" ] || return 1
  have_uid="$(stat -c '%u' "$path" 2>/dev/null)" || return 1
  [ "$have_uid" = "$owner" ] || return 1
  return 0
}
# Exactly one canonical row matching regex; prints the row, rejects extras/NUL/CR.
retention_canonical_row() {
  local file="$1" regex="$2" row
  IFS= read -r row < "$file" || return 1
  [[ "$row" =~ $regex ]] || return 1
  printf '%s\n' "$row" | cmp -s -- "$file" - || return 1
  printf '%s' "$row"
  return 0
}
# Validates one rollback or quarantine candidate. Logs untrusted/corrupt
# warning, returns 0 valid, 1 untrusted/unsafe, 2 corrupt rollback image.
# Caller must enable nullglob; listing uses /* + /.* so dotglob is untouched.
# Trusted rollback shape is exactly 4 files for both modes
# (naga-control-installer-backup-v1 contract shared with the uninstaller).
retention_valid_candidate() {
  local candidate="$1" kind="$2" owner="$3" row digest tag_row name e b
  local entries=()
  local -a lines
  retention_owned_dir "$candidate" "$owner" || { log "warning: retention left untrusted $kind $candidate for manual inspection"; return 1; }
  for e in "$candidate"/* "$candidate"/.*; do
    b="${e##*/}"
    [ "$b" = . ] && continue
    [ "$b" = .. ] && continue
    entries+=("$e")
  done
  if [ "$kind" = rollback ]; then
    [ "${#entries[@]}" -eq 4 ] || { log "warning: retention left untrusted rollback $candidate for manual inspection"; return 1; }
    for e in "${entries[@]}"; do
      b="${e##*/}"
      case "$b" in
        naga-control.AppImage|installed-tag|image.sha256|installer-backup) ;;
        *) log "warning: retention left untrusted rollback $candidate for manual inspection"; return 1 ;;
      esac
    done
    for name in naga-control.AppImage installed-tag image.sha256 installer-backup; do
      retention_owned_file "$candidate/$name" "$owner" || { log "warning: retention left untrusted rollback $candidate for manual inspection"; return 1; }
    done
    row="$(retention_canonical_row "$candidate/installer-backup" '^naga-control-installer-backup-v1$')" || { log "warning: retention left untrusted rollback $candidate for manual inspection"; return 1; }
    tag_row="$(retention_canonical_row "$candidate/installed-tag" '^[a-zA-Z0-9][a-zA-Z0-9._+-]*$')" || { log "warning: retention left untrusted rollback $candidate for manual inspection"; return 1; }
    row="$(retention_canonical_row "$candidate/image.sha256" '^[0-9a-f]{64}\ \ naga-control\.AppImage$')" || { log "warning: retention left untrusted rollback $candidate for manual inspection"; return 1; }
    digest="${row:0:64}"
    probe_image "$candidate/naga-control.AppImage" "$digest" || { log "warning: retention kept corrupt rollback $candidate for manual inspection"; return 2; }
  else
    [ "${#entries[@]}" -eq 3 ] || { log "warning: retention left untrusted quarantine $candidate for manual inspection"; return 1; }
    for e in "${entries[@]}"; do
      b="${e##*/}"
      case "$b" in
        naga-control.AppImage|installed-tag|quarantine) ;;
        *) log "warning: retention left untrusted quarantine $candidate for manual inspection"; return 1 ;;
      esac
    done
    for name in naga-control.AppImage installed-tag quarantine; do
      retention_owned_file "$candidate/$name" "$owner" || { log "warning: retention left untrusted quarantine $candidate for manual inspection"; return 1; }
    done
    tag_row="$(retention_canonical_row "$candidate/installed-tag" '^[a-zA-Z0-9][a-zA-Z0-9._+-]*$')" || { log "warning: retention left untrusted quarantine $candidate for manual inspection"; return 1; }
    mapfile -t lines < "$candidate/quarantine" || { log "warning: retention left untrusted quarantine $candidate for manual inspection"; return 1; }
    [ "${#lines[@]}" -eq 4 ] || { log "warning: retention left untrusted quarantine $candidate for manual inspection"; return 1; }
    [ "${lines[0]}" = "naga-control-installer-quarantine-v1" ] || { log "warning: retention left untrusted quarantine $candidate for manual inspection"; return 1; }
    [ "${lines[1]}" = "UNVERIFIED previous image: not verified against release sidecar; not a rollback pair; manual recovery only" ] || { log "warning: retention left untrusted quarantine $candidate for manual inspection"; return 1; }
    [ "${lines[2]}" = "observed unavailable UNVERIFIED" ] || [[ "${lines[2]}" =~ ^observed\ [0-9a-f]{64}\ UNVERIFIED$ ]] || { log "warning: retention left untrusted quarantine $candidate for manual inspection"; return 1; }
    [ "${lines[3]}" = "tag $tag_row" ] || { log "warning: retention left untrusted quarantine $candidate for manual inspection"; return 1; }
    printf '%s\n' "${lines[0]}" "${lines[1]}" "${lines[2]}" "${lines[3]}" | cmp -s -- "$candidate/quarantine" - || { log "warning: retention left untrusted quarantine $candidate for manual inspection"; return 1; }
  fi
  return 0
}
# Best-effort exact removal of known files then rmdir.
retention_remove_exact() {
  local candidate="$1" owner="$2"
  shift 2
  local entries=() e b name rm_args=() found
  retention_owned_dir "$candidate" "$owner" || { log "warning: retention cleanup incomplete for $candidate"; return 1; }
  for e in "$candidate"/* "$candidate"/.*; do
    b="${e##*/}"
    [ "$b" = . ] && continue
    [ "$b" = .. ] && continue
    entries+=("$e")
  done
  [ "${#entries[@]}" -eq "$#" ] || { log "warning: retention cleanup incomplete for $candidate"; return 1; }
  for e in "${entries[@]}"; do
    b="${e##*/}"
    found=0
    for name in "$@"; do [ "$b" = "$name" ] && { found=1; break; }; done
    [ "$found" -eq 1 ] || { log "warning: retention cleanup incomplete for $candidate"; return 1; }
  done
  for name in "$@"; do
    retention_owned_file "$candidate/$name" "$owner" || { log "warning: retention cleanup incomplete for $candidate"; return 1; }
  done
  for name in "$@"; do
    rm_args+=("$candidate/$name")
  done
  rm -f -- "${rm_args[@]}" || { log "warning: retention cleanup incomplete for $candidate"; return 1; }
  rmdir -- "$candidate" || { log "warning: retention cleanup incomplete for $candidate"; return 1; }
  return 0
}
# Post-commit retention: keep one verified rollback, remove owned quarantines.
# Best effort, always 0; only exact known files unlinked then rmdir, re-checked
# before unlink. Never touches profiles, live files, lock, or unknown files.
prune_retention() {
  local candidate base="" keep="" best_mtime="" best_name="" mtime mtime_failed=0 skip_rollback_prune=""
  local valid_rollbacks=() valid_quarantines=() desktop_uid="" old_nullglob=""
  desktop_uid="$(id -u 2>/dev/null)" || {
    log "warning: retention cleanup incomplete; could not verify ownership"
    return 0
  }
  [[ "$desktop_uid" =~ ^[0-9]+$ ]] || {
    log "warning: retention cleanup incomplete; could not verify ownership"
    return 0
  }
  if shopt -q nullglob; then old_nullglob="shopt -s nullglob"; else old_nullglob="shopt -u nullglob"; fi
  shopt -s nullglob
  for candidate in "$STATE_DIR"/rollback.*; do
    [ -e "$candidate" ] || [ -L "$candidate" ] || continue
    retention_valid_candidate "$candidate" rollback "$desktop_uid" && valid_rollbacks+=("$candidate") || true
  done
  for candidate in "$STATE_DIR"/quarantine.*; do
    [ -e "$candidate" ] || [ -L "$candidate" ] || continue
    retention_valid_candidate "$candidate" quarantine "$desktop_uid" && valid_quarantines+=("$candidate") || true
  done
  keep=""
  if [ -n "$BACKUP" ]; then
    for candidate in "${valid_rollbacks[@]}"; do
      if [ "$candidate" = "$BACKUP" ]; then
        keep="$BACKUP"
        break
      fi
    done
    if [ -z "$keep" ]; then
      log "warning: retention left current backup $BACKUP for manual inspection; keeping existing snapshots"
      skip_rollback_prune=1
    fi
  fi
  if [ -z "$keep" ] && [ -z "$skip_rollback_prune" ] && [ "${#valid_rollbacks[@]}" -gt 0 ]; then
    best_mtime=""; best_name=""; mtime_failed=0
    for candidate in "${valid_rollbacks[@]}"; do
      mtime="$(stat -c '%Y' "$candidate" 2>/dev/null)" || {
        log "warning: retention left $candidate for manual inspection"
        mtime_failed=1
        continue
      }
      [[ "$mtime" =~ ^[0-9]+$ ]] || {
        log "warning: retention left $candidate for manual inspection"
        mtime_failed=1
        continue
      }
      base="${candidate##*/}"
      if [ -z "$keep" ] || [ "$mtime" -gt "$best_mtime" ] || { [ "$mtime" -eq "$best_mtime" ] && [[ "$base" > "$best_name" ]]; }; then
        best_mtime="$mtime"
        best_name="$base"
        keep="$candidate"
      fi
    done
    if [ "$mtime_failed" -ne 0 ]; then
      log "warning: retention kept existing verified rollbacks for manual inspection; could not determine newest"
      skip_rollback_prune=1
      keep=""
    fi
  fi
  if [ -z "$skip_rollback_prune" ] && [ -n "$keep" ]; then
    log "cleanup: keeping newest verified rollback $keep"
  fi
  if [ -z "$skip_rollback_prune" ]; then
    for candidate in "${valid_rollbacks[@]}"; do
      [ "$candidate" = "$keep" ] && continue
      retention_remove_exact "$candidate" "$desktop_uid" naga-control.AppImage installed-tag image.sha256 installer-backup && log "cleanup: removed older verified rollback $candidate" || true
    done
  fi
  for candidate in "${valid_quarantines[@]}"; do
    retention_remove_exact "$candidate" "$desktop_uid" naga-control.AppImage installed-tag quarantine && log "cleanup: removed unverified quarantine $candidate" || true
  done
  eval "$old_nullglob" || true
  return 0
}
handle_unverified_failure() {
  if [ "${SERVICE_MANAGER:-systemd}" = "session" ]; then
    session_handle_unverified_failure
    return $?
  fi
  local failed=0 disable_failed=0
  log "installation failed: unverified previous image; manual recovery required (no automatic rollback of unverified bytes)"
  if ! ensure_stopped; then
    systemctl --user stop naga-control.service 9>&- || failed=1
    if ! ensure_stopped; then
      echo "RESTORATION FAILED: Naga did not become inactive; partial files retained; manual recovery required" >&2
      [ -n "$QUARANTINE" ] && echo "unverified quarantine retained: $QUARANTINE" >&2
      return 1
    fi
  fi
  systemctl --user disable naga-control.service 9>&- || { failed=1; disable_failed=1; }
  if [ "$disable_failed" -eq 1 ]; then
    echo "warning: could not disable Naga service; manual recovery required" >&2
  fi
  if [ "$DEPENDENCIES_STARTED" -eq 1 ]; then
    echo "error: Naga remains stopped; OpenRazer step failed/was interrupted, possible partial package changes; inspect inventory before reboot/re-login" >&2
  fi
  if [ -n "$QUARANTINE" ]; then
    echo "unverified previous image preserved at $QUARANTINE (not a verified rollback); manual recovery required" >&2
  else
    echo "unverified previous image; manual recovery required (no verified rollback available)" >&2
  fi
  if [ "$disable_failed" -eq 1 ]; then
    echo "partial state retained; profiles were not changed; Naga left stopped but not disabled; inspect AppImage/tag/integration manually" >&2
  else
    echo "partial state retained; profiles were not changed; Naga left stopped and disabled; inspect AppImage/tag/integration manually" >&2
  fi
  [ "$failed" -eq 0 ]
}
session_handle_unverified_failure() {
  local failed=0
  log "installation failed: unverified previous image; manual recovery required (no automatic rollback of unverified bytes)"
  ensure_session_helper || { echo "RESTORATION FAILED: session helper unavailable; activation remains fenced; manual recovery required" >&2; [ -n "$QUARANTINE" ] && echo "unverified quarantine retained: $QUARANTINE" >&2; return 1; }
  if ! session_reapply_fence; then
    echo "warning: session fence uncertain; activation may not be fenced; manual recovery required" >&2
  fi
  if ! ensure_stopped; then
    if ! naga_session_stop >/dev/null 2>&1 9>&-; then
      failed=1
    fi
    if ! ensure_stopped; then
      echo "RESTORATION FAILED: session did not become inactive; activation remains fenced; manual recovery required" >&2
      [ -n "$QUARANTINE" ] && echo "unverified quarantine retained: $QUARANTINE" >&2
      if [ -n "${RECOVERY_DIR:-}" ]; then
        echo "operator recovery snapshot retained: $RECOVERY_DIR" >&2
      fi
      return 1
    fi
  fi
  if [ -n "$QUARANTINE" ]; then
    echo "unverified previous image preserved at $QUARANTINE (not a verified rollback); manual recovery required" >&2
  else
    echo "unverified previous image; manual recovery required (no verified rollback available)" >&2
  fi
  if session_is_fenced; then
    echo "session activation remains fenced; files and backups retained for manual recovery; profiles were not changed" >&2
  else
    echo "session fence uncertain; files and backups retained for manual recovery; profiles were not changed" >&2
  fi
  if [ -n "${RECOVERY_DIR:-}" ]; then
    echo "operator recovery snapshot retained: $RECOVERY_DIR" >&2
  fi
  [ "$failed" -eq 0 ]
}
cleanup() {
  local status=$?
  trap - EXIT HUP INT TERM
  if [ "$status" -ne 0 ] && [ "$COMMITTED" -eq 1 ]; then
    echo "warning: installation already committed; post-install cleanup interrupted/failed (status $status)" >&2
  elif [ "$status" -ne 0 ]; then
    if [ "$TOUCHED" -eq 1 ] && [ "$COMMITTED" -eq 0 ]; then
      if [ "$HAD_PREVIOUS_IMAGE" -eq 1 ] && [ "$OLD_VERIFIED" -eq 0 ]; then
        handle_unverified_failure || true
      else
        restore || true
      fi
    elif [ "$COMMITTED" -eq 0 ] && [ "$HAD_PREVIOUS_IMAGE" -eq 1 ] && [ "$OLD_VERIFIED" -eq 0 ] && { [ -n "$QUARANTINE" ] || [ "$STOPPED" -eq 1 ] || [ "$DEPENDENCIES_STARTED" -eq 1 ]; }; then
      handle_unverified_failure || true
    elif [ "$COMMITTED" -eq 0 ] && { [ "$STOPPED" -eq 1 ] || [ "$DEPENDENCIES_STARTED" -eq 1 ]; }; then
      if [ "$DEPENDENCIES_STARTED" -eq 1 ]; then
        if [ "${SERVICE_MANAGER:-systemd}" = "session" ]; then
          if ! ensure_stopped; then
            ensure_session_helper 2>/dev/null && naga_session_stop >/dev/null 2>&1 9>&- && ensure_stopped \
              || echo "RESTORATION FAILED: session could not be kept inactive after the prerequisite failure" >&2
          fi
          if ensure_stopped; then
            echo "error: Naga remains stopped; inspect session state before activation" >&2
          else
            echo "error: Naga is not safely stopped; stop it manually and inspect session state before activation" >&2
          fi
          if [ -n "${RECOVERY_DIR:-}" ]; then
            echo "operator recovery snapshot retained: $RECOVERY_DIR" >&2
          fi
        else
          if ! ensure_stopped; then
            systemctl --user stop naga-control.service 9>&- && ensure_stopped \
              || echo "RESTORATION FAILED: Naga could not be kept inactive after the prerequisite failure" >&2
          fi
          if ensure_stopped; then
            echo "error: Naga remains stopped; OpenRazer step failed/was interrupted, possible partial package changes; inspect inventory before reboot/re-login" >&2
          else
            echo "error: Naga is not safely stopped; OpenRazer may have partial changes; stop it manually and inspect inventory before activation" >&2
          fi
        fi
      elif [ "$WAS_ACTIVE" -eq 1 ] || [ "$SESSION_WAS_ACTIVE" -eq 1 ]; then
        if [ "${SERVICE_MANAGER:-systemd}" = "session" ]; then
          if [ "$OLD_VERIFIED" -eq 1 ]; then
            restore || true
            if [ -n "${RECOVERY_DIR:-}" ]; then
              echo "operator recovery snapshot retained: $RECOVERY_DIR" >&2
            fi
          else
            echo "error: session stopped and fenced; unverified previous cannot be restored; manual recovery required" >&2
            if [ -n "${RECOVERY_DIR:-}" ]; then
              echo "operator recovery snapshot retained: $RECOVERY_DIR" >&2
            fi
          fi
        else
          log "previous app/integration files unchanged; resuming the previous Naga service"
          systemctl --user start naga-control.service 9>&- && [ "$(active_state)" = active ] \
            || echo "RESTORATION FAILED: previous service could not resume" >&2
        fi
      fi
    fi
    if [ "${SERVICE_MANAGER:-}" = "session" ] && [ -n "${RECOVERY_DIR:-}" ] && [ -d "${RECOVERY_DIR:-}" ]; then
      echo "operator recovery snapshot retained: $RECOVERY_DIR" >&2
    fi
    echo "error: installation not completed" >&2
  fi
  if [ "$status" -eq 0 ] && [ "$COMMITTED" -eq 1 ]; then
    [ -z "${RECOVERY_DIR:-}" ] || rm -rf -- "$RECOVERY_DIR" || true
    RECOVERY_DIR=""
  fi
  [ "${#SIBLINGS[@]}" -eq 0 ] || rm -f -- "${SIBLINGS[@]}" || true
  [ -z "$BACKUP_PENDING" ] || rm -rf -- "$BACKUP_PENDING" || true
  [ -z "$QUARANTINE_PENDING" ] || rm -rf -- "$QUARANTINE_PENDING" || true
  [ -z "${RECOVERY_PENDING:-}" ] || rm -rf -- "$RECOVERY_PENDING" || true
  [ -z "$STAGE" ] || rm -rf -- "$STAGE" || true
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
mkdir -p "$STATE_DIR"
if ! { [ -O "$STATE_DIR" ] && { [ ! -e "$STATE_DIR/install.lock" ] || [ -O "$STATE_DIR/install.lock" ]; }; }; then
  die "installer lock directory/file must belong to the desktop user"
fi
lock_mode="$(stat -Lc '%a' "$STATE_DIR")" || die "could not inspect installer lock directory permissions"
if ! { [[ "$lock_mode" =~ ^[0-7]{3,4}$ ]] && (( (8#$lock_mode & 0022) == 0 )); }; then
  die "installer lock directory must not be group/other writable; fix its permissions manually"
fi
exec 9>>"$STATE_DIR/install.lock"
flock -n 9 || die "another Naga installer is running; wait for it to finish"
# Authority revalidation under lock: a cooperating uninstall+fresh install can
# change the canonical manager while this operation waited in preflight. The
# early selection above stays for read-only tool preflight compatibility; the
# locked value wins and any change fails closed before downloads or mutations.
PRELOCK_PRIOR_MODE="$PRIOR_MODE"
PRELOCK_SERVICE_MANAGER="$SERVICE_MANAGER"
prior_mode_detect || die "service manager is misconfigured; resolve it manually before installation"
LOCK_NOW_PRIOR_MODE="$PRIOR_MODE"
if [ "$LOCK_NOW_PRIOR_MODE" != "$PRELOCK_PRIOR_MODE" ]; then
  PRIOR_MODE="$PRELOCK_PRIOR_MODE"
  SERVICE_MANAGER="$PRELOCK_SERVICE_MANAGER"
  was="${PRELOCK_PRIOR_MODE:-fresh}"
  now="${LOCK_NOW_PRIOR_MODE:-fresh}"
  die "service manager changed while waiting for the installer lock (was '$was' now '$now'); rerun the same command; Naga unchanged"
fi
PRIOR_MODE="$PRELOCK_PRIOR_MODE"
SERVICE_MANAGER="$PRELOCK_SERVICE_MANAGER"
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/naga-install.XXXXXX")"
# FD 9 stays with the installer and its foreground prerequisite helper only.
# AppImage, sudo, systemctl, dbus-send and sleep children close their copies
# before activation.
if [ -z "$VERSION" ]; then
  resolved="$(curl -fsSL -o /dev/null -w '%{url_effective}' "https://github.com/$REPO/releases/latest")" \
    || die "could not resolve the latest release; pass --version <tag>"
  VERSION="${resolved##*/}"
fi
[[ "$VERSION" =~ ^[a-zA-Z0-9][a-zA-Z0-9._+-]*$ ]] || die "invalid release tag"
fetch_digest() {
  local tag="$1" destination="$2" row
  curl -fsSL -o "$destination" "https://github.com/$REPO/releases/download/$tag/$ASSET.sha256" \
    || die "missing AppImage checksum for $tag; older releases without the sidecar cannot be installed safely by this installer"
  # Compare exact bytes with a canonical reconstruction: catches extra rows,
  # blank lines, NUL/CR, missing newline, binary-mode markers and traversal.
  IFS= read -r row < "$destination" || die "malformed AppImage checksum for $tag"
  [[ "$row" =~ ^[0-9a-f]{64}\ \ Naga-Control-x86_64\.AppImage$ ]] || die "malformed AppImage checksum for $tag"
  printf '%s\n' "$row" > "$destination.canonical"
  cmp -s "$destination" "$destination.canonical" || die "AppImage checksum must contain exactly one canonical row"
  DIGEST="${row:0:64}"
}
verify_image() {
  local image="$1" expected="$2" actual
  [ -s "$image" ] || die "AppImage is empty: $image"
  actual="$(sha256sum "$image")" || die "could not hash AppImage"
  [ "${actual:0:64}" = "$expected" ] || die "AppImage checksum mismatch: $image; no execution or replacement permitted"
}
fetch_old_digest() {
  local tag="$1" destination="$2" row
  curl -fsSL -o "$destination" "https://github.com/$REPO/releases/download/$tag/$ASSET.sha256" || return 1
  IFS= read -r row < "$destination" || return 1
  [[ "$row" =~ ^[0-9a-f]{64}\ \ Naga-Control-x86_64\.AppImage$ ]] || return 1
  printf '%s\n' "$row" > "$destination.canonical" || return 1
  cmp -s "$destination" "$destination.canonical" || return 1
  DIGEST="${row:0:64}"
}
probe_image() {
  local image="$1" expected="$2" actual
  [ -s "$image" ] || return 1
  actual="$(sha256sum "$image")" || return 1
  [ "${actual:0:64}" = "$expected" ]
}
observe_image() {
  local image="$1" actual
  [ -f "$image" ] || return 1
  actual="$(sha256sum "$image" 2>/dev/null)" || return 1
  printf '%s' "${actual:0:64}"
}
fetch_digest "$VERSION" "$STAGE/app.sha256"
NEW_DIGEST="$DIGEST"
INSTALLED_TAG=""
if [ -f "$STAMP" ]; then
  IFS= read -r INSTALLED_TAG < "$STAMP" || die "invalid installed-tag"
  printf '%s\n' "$INSTALLED_TAG" > "$STAGE/previous-tag.canonical"
  cmp -s "$STAMP" "$STAGE/previous-tag.canonical" || die "invalid installed-tag (expected one canonical tag row)"
fi
if [ -f "$APPIMAGE_DST" ]; then
  HAD_PREVIOUS_IMAGE=1
  [[ "$INSTALLED_TAG" =~ ^[a-zA-Z0-9][a-zA-Z0-9._+-]*$ ]] || die "existing image has no valid installed-tag; preserve it and arrange manual recovery"
  if [ "$INSTALLED_TAG" = "$VERSION" ]; then
    OLD_DIGEST="$NEW_DIGEST"
    if probe_image "$APPIMAGE_DST" "$OLD_DIGEST"; then
      OLD_VERIFIED=1
    else
      OLD_OBSERVED="$(observe_image "$APPIMAGE_DST" || true)"
      log "warning: existing $INSTALLED_TAG image checksum mismatch (expected $OLD_DIGEST${OLD_OBSERVED:+, observed $OLD_OBSERVED}); replacing with verified $VERSION image; previous bytes preserved as unverified quarantine, not a verified rollback"
    fi
  else
    if fetch_old_digest "$INSTALLED_TAG" "$STAGE/previous.sha256"; then
      OLD_DIGEST="$DIGEST"
      if probe_image "$APPIMAGE_DST" "$OLD_DIGEST"; then
        OLD_VERIFIED=1
      else
        OLD_OBSERVED="$(observe_image "$APPIMAGE_DST" || true)"
        log "warning: existing $INSTALLED_TAG image checksum mismatch (expected $OLD_DIGEST${OLD_OBSERVED:+, observed $OLD_OBSERVED}); replacing with verified $VERSION image $NEW_DIGEST; previous bytes preserved as unverified quarantine, not a verified rollback"
      fi
    else
      OLD_DIGEST=""
      OLD_OBSERVED="$(observe_image "$APPIMAGE_DST" || true)"
      log "warning: previous $INSTALLED_TAG checksum unavailable; cannot verify existing image${OLD_OBSERVED:+ (observed $OLD_OBSERVED)}; replacing with verified $VERSION image $NEW_DIGEST; previous bytes preserved as unverified quarantine, not a verified rollback"
    fi
  fi
fi
if [ -f "$APPIMAGE_DST" ] && [ "$INSTALLED_TAG" = "$VERSION" ] && [ "$OLD_VERIFIED" -eq 1 ] && [ -z "${NAGA_CONTROL_FORCE_DOWNLOAD:-}" ]; then
  log "AppImage $VERSION already present; verified local bytes before reuse"
  cp -p "$APPIMAGE_DST" "$STAGE/$ASSET"
else
  curl -fsSL -o "$STAGE/$ASSET" "https://github.com/$REPO/releases/download/$VERSION/$ASSET" || die "AppImage download failed"
fi
verify_image "$STAGE/$ASSET" "$NEW_DIGEST"
chmod 755 "$STAGE/$ASSET"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UDEV_SRC="$SCRIPT_DIR/../system/udev/70-naga-control.rules"
if [ ! -f "$UDEV_SRC" ]; then
  UDEV_SRC="$STAGE/70-naga-control.rules"
  curl -fsSL -o "$UDEV_SRC" "https://raw.githubusercontent.com/$REPO/$VERSION/system/udev/70-naga-control.rules" \
    || curl -fsSL -o "$UDEV_SRC" "https://raw.githubusercontent.com/$REPO/$VERSION/packaging/udev/70-naga-control.rules" \
    || die "could not download the udev rule for $VERSION"
fi
[ -s "$UDEV_SRC" ] || die "empty udev rule"
if [ "$SERVICE_MANAGER" = "session" ]; then
  # Managed session install/update: fence activation before clean stop,
  # stage new payload before stop to reject old releases early, replace only
  # after safe stop, restore direct activation before start. No systemctl,
  # busctl, or backend helpers are used here; only dbus-send/sleep via the
  # trusted sibling helper. Profiles are never touched.
  ensure_session_helper || die "session helper is missing; refusing session installation"
  log "session mode: staging new integration before stop to validate payload capability"
  mkdir -p "$STAGE/integration-home/.local/bin" "$STAGE/udev" || die "could not stage session integration"
  mkdir -p "$STAGE/integration-config/autostart" || die "could not stage session integration"
  STAGE_CONFIG="$STAGE/integration-config"
  if ! "$STAGE/$ASSET" --install --home "$STAGE/integration-home" --config-home "$STAGE_CONFIG" --exec-prefix "$APPIMAGE_DST" --udev-dir "$STAGE/udev" --service-manager session 9>&- >/dev/null; then
    die "session integration failed: installed image lacks --service-manager session support; need a new build/release with session integration (older published images cannot be used); Naga unchanged"
  fi
  printf '#!/usr/bin/env bash\nexec %q gui "$@"\n' "$APPIMAGE_DST" > "$STAGE/integration-home/.local/bin/naga-control" || die "could not stage session wrapper"
  chmod 755 "$STAGE/integration-home/.local/bin/naga-control" || die "could not stage session wrapper"
  for path in "${SESSION_HOME_FILES[@]}"; do
    [ -f "$STAGE/integration-home/$path" ] && [ ! -L "$STAGE/integration-home/$path" ] || die "session integration failed: missing/unsafe staged file $path; need a new build/release; Naga unchanged"
  done
  [ -f "$STAGE_CONFIG/autostart/$SERVICE_AUTOSTART_NAME" ] && [ ! -L "$STAGE_CONFIG/autostart/$SERVICE_AUTOSTART_NAME" ] || die "session integration failed: missing staged autostart; need a new build/release; Naga unchanged"
  [ -f "$STAGE/udev/70-naga-control.rules" ] || die "session integration failed: missing staged udev rule; Naga unchanged"
  staged_activation="$STAGE/integration-home/.local/share/dbus-1/services/org.nagacontrol.Service1.service"
  activation_session_owned "$staged_activation" || die "session integration failed: staged activation is not owned; need a new build/release; Naga unchanged"
  # shellcheck disable=SC2016
  grep -qF "$APPIMAGE_DST" "$staged_activation" 2>/dev/null || die "session integration failed: staged activation does not point at the new image; Naga unchanged"
  staged_autostart="$STAGE_CONFIG/autostart/$SERVICE_AUTOSTART_NAME"
  service_autostart_owned "$staged_autostart" || die "session integration failed: staged autostart is not owned; Naga unchanged"
  grep -qF "$APPIMAGE_DST" "$staged_autostart" 2>/dev/null || die "session integration failed: staged autostart does not point at the new image; Naga unchanged"
  # Query incumbent session state before any mutation.
  session_state="$(active_state)" || die "session bus is unknown; refusing without replacing image; manual recovery required"
  case "$session_state" in
    active) WAS_ACTIVE=1; SESSION_WAS_ACTIVE=1 ;;
    inactive) ;;
    *) die "session service state is $session_state; resolve it manually before installation" ;;
  esac
  log "Quit the Naga GUI and release all held mouse controls before proceeding; GUI processes are never killed."
  # Snapshot previous user-owned files only, never profiles or package state.
  for path in ".local/bin/naga-control.AppImage" ".local/share/naga-control/installed-tag" ".local/share/naga-control/service-manager" ".local/share/naga-control/session-service.sh" "${SESSION_HOME_FILES[@]}"; do
    if [ -f "$HOME/$path" ]; then
      mkdir -p "$STAGE/previous/$(dirname "$path")" || die "could not snapshot previous files"
      cp -p "$HOME/$path" "$STAGE/previous/$path" || die "could not snapshot previous files"
    fi
  done
  rel_autostart="${SESSION_AUTOSTART_LIVE#"$HOME"/}"
  if [ "$rel_autostart" != "$SESSION_AUTOSTART_LIVE" ] && [ -f "$SESSION_AUTOSTART_LIVE" ]; then
    mkdir -p "$STAGE/previous/$(dirname "$rel_autostart")" || die "could not snapshot previous autostart"
    cp -p "$SESSION_AUTOSTART_LIVE" "$STAGE/previous/$rel_autostart" || die "could not snapshot previous autostart"
  fi
  if [ "$WAS_ACTIVE" -eq 1 ]; then
    log "Naga session is running: graceful stop temporarily disables remapping; success resumes it."
    if [ "$RESTART_SERVICE" -ne 1 ]; then
      [ -t 0 ] || die "installation canceled: running session needs terminal consent or explicit --restart-service"
      answer=""
      read -r -p "Gracefully stop Naga session for this upgrade? [y/N] " answer || true
      case "$answer" in [yY]|[yY][eE][sS]) ;; *) die "installation canceled: Naga stop declined" ;; esac
    fi
    session_fence_activation || die "session fence failed; Naga image was not replaced; activation remains fenced for manual recovery"
    if ! naga_session_stop 9>&- >/dev/null; then
      die "session stop failed (PrepareShutdown/Exit/verify); activation remains fenced; Naga image was not replaced"
    fi
    ensure_stopped || die "session stop unfinished/failed; must be inactive before replacement; activation remains fenced"
    STOPPED=1
  else
    if [ -n "$PRIOR_MODE" ]; then
      session_fence_activation || die "session fence failed; Naga image was not replaced; activation remains fenced for manual recovery"
    fi
    ensure_stopped || die "session became active; quit the GUI before replacing the image"
  fi
  if [ "$HAD_PREVIOUS_IMAGE" -eq 1 ] && [ "$OLD_VERIFIED" -eq 1 ]; then
    if ! probe_image "$STAGE/previous/.local/bin/naga-control.AppImage" "$OLD_DIGEST"; then
      OLD_VERIFIED=0
      OLD_OBSERVED="$(observe_image "$STAGE/previous/.local/bin/naga-control.AppImage" || true)"
      log "warning: previous image changed after stop (expected $OLD_DIGEST${OLD_OBSERVED:+, observed $OLD_OBSERVED}); treating as unverified quarantine, not a verified rollback"
    fi
  fi
  if [ "$HAD_PREVIOUS_IMAGE" -eq 1 ] && [ "$OLD_VERIFIED" -eq 0 ]; then
    publish_quarantine || die "could not preserve unverified previous image; session stopped and fenced; manual recovery required"
  fi
  ensure_stopped || die "session became active again; quit the GUI before replacing the image"
  for path in "${SESSION_HOME_FILES[@]}"; do
    safe_file "$HOME/$path"
  done
  safe_file "$SESSION_AUTOSTART_LIVE"
  safe_file "$APPIMAGE_DST"
  safe_file "$STAMP"
  safe_file "$SERVICE_MANAGER_FILE"
  safe_file "$SESSION_HELPER_DST"
  if [ -f "$APPIMAGE_DST" ] && { [ "$INSTALLED_TAG" != "$VERSION" ] || [ "$OLD_DIGEST" != "$NEW_DIGEST" ] || [ -n "${NAGA_CONTROL_FORCE_DOWNLOAD:-}" ] || [ "$OLD_VERIFIED" -eq 0 ]; }; then
    if [ "$OLD_VERIFIED" -eq 1 ]; then
      BACKUP_PENDING="$(mktemp -d "$STATE_DIR/.rollback.XXXXXX")" || die "could not stage rollback"
      cp -p "$STAGE/previous/.local/bin/naga-control.AppImage" "$BACKUP_PENDING/naga-control.AppImage" || die "could not stage rollback"
      cp -p "$STAGE/previous/.local/share/naga-control/installed-tag" "$BACKUP_PENDING/installed-tag" || die "could not stage rollback"
      verify_image "$BACKUP_PENDING/naga-control.AppImage" "$OLD_DIGEST" || die "previous image changed; manual recovery required"
      printf '%s  naga-control.AppImage\n' "$OLD_DIGEST" > "$BACKUP_PENDING/image.sha256" || die "could not stage rollback"
      printf 'naga-control-installer-backup-v1\n' > "$BACKUP_PENDING/installer-backup" || die "could not stage rollback"
      BACKUP="$STATE_DIR/rollback.${BACKUP_PENDING##*.}"
      [ ! -e "$BACKUP" ] && [ ! -L "$BACKUP" ] || die "rollback destination already exists"
      mv -T "$BACKUP_PENDING" "$BACKUP" || die "could not publish rollback pair"
      BACKUP_PENDING=""
      log "verified rollback pair retained: $BACKUP (not a package/system rollback)"
    elif [ -z "$QUARANTINE" ]; then
      publish_quarantine || die "could not preserve unverified previous image; manual recovery required"
    else
      log "unverified quarantine already retained: $QUARANTINE"
    fi
  fi
  TOUCHED=1
  atomic_copy "$STAGE/$ASSET" "$APPIMAGE_DST" || die "atomic AppImage replacement failed"
  printf '%s\n' "$VERSION" > "$STAGE/installed-tag" || die "could not stage tag"
  atomic_copy "$STAGE/installed-tag" "$STAMP" || die "installed-tag replacement failed"
  printf 'session\n' > "$STAGE/service-manager" || die "could not stage service manager"
  atomic_copy "$STAGE/service-manager" "$SERVICE_MANAGER_FILE" || die "service-manager replacement failed"
  chmod 600 "$SERVICE_MANAGER_FILE" || die "service-manager permissions failed"
  cp -p "${SCRIPT_DIR}/session_service.sh" "$STAGE/session-service.sh" || die "could not stage session helper"
  [ -s "$STAGE/session-service.sh" ] || die "empty session helper"
  atomic_copy "$STAGE/session-service.sh" "$SESSION_HELPER_DST" || die "session helper replacement failed"
  chmod 700 "$SESSION_HELPER_DST" || die "session helper permissions failed"
  for path in ".local/bin/naga-control" ".local/share/applications/org.nagacontrol.NagaControl.desktop" ".local/share/icons/hicolor/64x64/apps/org.nagacontrol.NagaControl.png" ".local/share/icons/hicolor/128x128/apps/org.nagacontrol.NagaControl.png" ".local/share/icons/hicolor/256x256/apps/org.nagacontrol.NagaControl.png" ".local/share/icons/hicolor/512x512/apps/org.nagacontrol.NagaControl.png"; do
    atomic_copy "$STAGE/integration-home/$path" "$HOME/$path" || die "session integration replacement failed: $path"
  done
  atomic_copy "$staged_activation" "$ACTIVATION_DST" || die "session activation replacement failed"
  atomic_copy "$staged_autostart" "$SESSION_AUTOSTART_LIVE" || die "session autostart replacement failed"
  sudo install -m 644 "$UDEV_SRC" /etc/udev/rules.d/70-naga-control.rules 9>&- || die "udev rule installation failed (system changes are not rolled back)"
  UDEV_PENDING=0
  if ! sudo udevadm control --reload 9>&-; then
    UDEV_PENDING=1
    log "udev reload failed: app staged, permissions pending; ask your administrator to reload rules and replug the mouse"
  fi
  if ! naga_session_reload >/dev/null 2>&1 9>&-; then
    die "session bus reload failed after replace; activation may remain fenced; manual recovery required"
  fi
  SESSION_FENCED=0
  if [ "$UDEV_PENDING" -eq 1 ]; then
    ensure_stopped || die "session became active while activation must remain deferred; quit the GUI and inspect prerequisites"
    log "installation staged: session service not started; reload/replug for pending udev permissions, then verify before starting"
  else
    if ! naga_session_start 9>&- >/dev/null; then
      die "session start failed; inspect session bus and seat permissions before activation"
    fi
    [ "$(active_state)" = active ] || die "session did not become active"
    log "app installed; session service running (NOT proof of hardware readiness). Replug the mouse if permissions changed."
  fi
  COMMITTED=1
  prune_retention || log "warning: retention cleanup incomplete; older snapshots left for manual inspection"
  log "Run '$WRAPPER_DST' to open the GUI after prerequisites are activated."
  echo "Verification (not executed by installer; may activate the service):"
  echo "bash $SESSION_HELPER_DST status"
  echo "Require session active, then physical F13/F14 DPI and F17 held-ALT down/up checks; installer success does not establish these."
  exit 0
fi
if [ "$INSTALL_OPENRAZER" -eq 1 ]; then
  offer_parse_identity
  if offer_arch_eligible; then
    OPENRAZER_HELPER_KIND="arch"
    ensure_arch_helper
    HELPER_BASE_ARGS=(--version "$VERSION")
    ensure_arch_dkms_ready
    log "checking optional OpenRazer install prerequisites before Naga stop consent"
    bash "$OPENRAZER_INSTALLER" "${HELPER_BASE_ARGS[@]}" --preflight 9>&- \
      || die "OpenRazer prerequisite preflight failed; Naga unchanged; opt-in requires a helper supporting --preflight (no legacy fallback)"
  elif offer_native_family; then
    if ! offer_native_eligible; then
      die "explicit OpenRazer setup unsupported on this host ($OFFER_ID); only experimental Arch/pacman and named Ubuntu/Debian, Fedora, openSUSE Leap/Tumbleweed are supported; Naga unchanged"
    fi
    offer_native_check_inventory
    if [ "$OFFER_NATIVE_INVENTORY" = "absent" ]; then
      offer_check_python
      if [ "$OFFER_PYTHON" = "absent" ]; then
        NATIVE_GATE="absent"
      elif [ "$OFFER_PYTHON" = "present" ]; then
        NATIVE_GATE="present"
      else
        NATIVE_GATE="unknown"
      fi
    elif [ "$OFFER_NATIVE_INVENTORY" = "present" ]; then
      NATIVE_GATE="present"
    else
      NATIVE_GATE="unknown"
    fi
    if [ "$NATIVE_GATE" != "absent" ]; then
      die "native first install refused: existing, partial, manual, or unknown OpenRazer detected; follow manual matching-cohort migration or the Arch-specific helper; Naga unchanged; no silent replacement"
    fi
    OPENRAZER_HELPER_KIND="native"
    ensure_native_helper
    HELPER_BASE_ARGS=(--family "$OFFER_NATIVE_FAMILY" --version "$VERSION" --code-ref "$NATIVE_CODE_REF")
    log "checking optional OpenRazer install prerequisites before Naga stop consent"
    bash "$OPENRAZER_INSTALLER" "${HELPER_BASE_ARGS[@]}" --preflight 9>&- \
      || die "OpenRazer prerequisite preflight failed; Naga unchanged; opt-in requires a helper supporting --preflight (no legacy fallback)"
  else
    die "explicit OpenRazer setup unsupported on this host ($OFFER_ID); only experimental Arch/pacman and named Ubuntu/Debian, Fedora, openSUSE Leap/Tumbleweed are supported; Naga unchanged"
  fi
else
  if [ "$OPENRAZER_HARD_SKIP" -eq 1 ] || [ "$OPENRAZER_EXPLICIT" -eq 1 ]; then
    log "app-only install: OpenRazer packages, group, and daemon are unchanged"
  else
    OFFER_STATUS="unknown"
    OPENRAZER_HELPER_KIND=""
    OFFER_NATIVE_FAMILY=""
    offer_parse_identity
    if offer_arch_eligible; then
      offer_check_inventory
      if [ "$OFFER_INVENTORY" = "absent" ]; then
        offer_check_python
        if [ "$OFFER_PYTHON" = "absent" ]; then
          OFFER_STATUS="arch-absent"
        elif [ "$OFFER_PYTHON" = "present" ]; then
          OFFER_STATUS="present"
        else
          OFFER_STATUS="unknown"
        fi
      elif [ "$OFFER_INVENTORY" = "present" ]; then
        OFFER_STATUS="present"
      else
        OFFER_STATUS="unknown"
      fi
    elif offer_native_eligible; then
      offer_native_check_inventory
      if [ "$OFFER_NATIVE_INVENTORY" = "absent" ]; then
        offer_check_python
        if [ "$OFFER_PYTHON" = "absent" ]; then
          OFFER_STATUS="native-absent"
        elif [ "$OFFER_PYTHON" = "present" ]; then
          OFFER_STATUS="present"
        else
          OFFER_STATUS="unknown"
        fi
      elif [ "$OFFER_NATIVE_INVENTORY" = "present" ]; then
        OFFER_STATUS="present"
      else
        OFFER_STATUS="unknown"
      fi
    elif [ "$OFFER_OS_STATUS" = "parsed" ]; then
      OFFER_STATUS="ineligible"
    else
      OFFER_STATUS="unknown"
    fi
    if [ "$OFFER_STATUS" = "arch-absent" ]; then
      if [ -t 0 ]; then
        log "OpenRazer backend absent: no installed packages or host imports detected"
        log "Experimental Arch setup offers pinned cohort 3.12.1.pr2904.fix2-1 from 26b0eeb5ed70d638fa3528851adcd5e58369a7f5 (sudo pacman -U, separate group consent, reboot/re-login required)"
        answer=""
        read -r -p "Install experimental pinned OpenRazer 3.12.1.pr2904.fix2-1 via sudo pacman -U (driver/daemon/client) with separate openrazer group consent and reboot/re-login required? [y/N] " answer || true
        case "$answer" in
          [yY]|[yY][eE][sS])
            INSTALL_OPENRAZER=1
            OPENRAZER_HELPER_KIND="arch"
            ensure_arch_helper
            HELPER_BASE_ARGS=(--version "$VERSION")
            ensure_arch_dkms_ready
            log "checking optional OpenRazer install prerequisites before Naga stop consent"
            bash "$OPENRAZER_INSTALLER" "${HELPER_BASE_ARGS[@]}" --preflight 9>&- \
              || die "OpenRazer prerequisite preflight failed; Naga unchanged; opt-in requires a helper supporting --preflight (no legacy fallback)"
            ;;
          *)
            log "app-only install: OpenRazer packages, group, and daemon are unchanged"
            log "OpenRazer is not installed; hardware prerequisites still missing. Rerun with --install-openrazer on experimental Arch/pacman for consented setup, or follow the manual matching-source route for other distributions. See docs/release-notes.md#required-openrazer. Installer success does not establish hardware readiness."
            ;;
        esac
      else
        log "app-only install: OpenRazer packages, group, and daemon are unchanged"
        log "OpenRazer is not installed; hardware prerequisites still missing. Rerun with --install-openrazer on experimental Arch/pacman for consented setup, or follow the manual matching-source route for other distributions. See docs/release-notes.md#required-openrazer. Installer success does not establish hardware readiness."
      fi
    elif [ "$OFFER_STATUS" = "native-absent" ]; then
      if [ -t 0 ]; then
        log "OpenRazer backend absent: no installed packages or host imports detected"
        log "Experimental $OFFER_NATIVE_FAMILY native setup builds pinned cohort 3.12.1.pr2904.fix2-1 from 26b0eeb5ed70d638fa3528851adcd5e58369a7f5 locally (consented build tools/active-kernel headers/stock OS repos + 3 local native packages, separate prerequisite/group consent, reboot/re-login required)"
        answer=""
        read -r -p "Build locally and install the native cohort (managers keep their prompts) with separate prerequisite/group consent and reboot/re-login required? [y/N] " answer || true
        case "$answer" in
          [yY]|[yY][eE][sS])
            INSTALL_OPENRAZER=1
            OPENRAZER_HELPER_KIND="native"
            ensure_native_helper
            HELPER_BASE_ARGS=(--family "$OFFER_NATIVE_FAMILY" --version "$VERSION" --code-ref "$NATIVE_CODE_REF")
            log "checking optional OpenRazer install prerequisites before Naga stop consent"
            bash "$OPENRAZER_INSTALLER" "${HELPER_BASE_ARGS[@]}" --preflight 9>&- \
              || die "OpenRazer prerequisite preflight failed; Naga unchanged; opt-in requires a helper supporting --preflight (no legacy fallback)"
            ;;
          *)
            log "app-only install: OpenRazer packages, group, and daemon are unchanged"
            log "OpenRazer is not installed; hardware prerequisites still missing. Rerun with --install-openrazer on named Ubuntu/Debian, Fedora, openSUSE Leap/Tumbleweed for consented local build, on experimental Arch/pacman for prebuilt setup, or follow the manual matching-source route for other distributions. See docs/release-notes.md#required-openrazer. Installer success does not establish hardware readiness."
            ;;
        esac
      else
        log "app-only install: OpenRazer packages, group, and daemon are unchanged"
        log "OpenRazer is not installed; hardware prerequisites still missing. Rerun with --install-openrazer on named Ubuntu/Debian, Fedora, openSUSE Leap/Tumbleweed for consented local build, on experimental Arch/pacman for prebuilt setup, or follow the manual matching-source route for other distributions. See docs/release-notes.md#required-openrazer. Installer success does not establish hardware readiness."
      fi
    elif [ "$OFFER_STATUS" = "present" ]; then
      log "app-only install: OpenRazer packages, group, and daemon are unchanged"
      log "Existing OpenRazer installation detected; leaving it unchanged (no automatic replacement). Presence alone does not prove hardware readiness. For reviewed reinstall use --install-openrazer only on Arch; on named native families an existing backend needs manual matching-cohort migration; see docs/release-notes.md#required-openrazer."
    else
      log "app-only install: OpenRazer packages, group, and daemon are unchanged"
      log "OpenRazer status unknown or host not eligible for automatic Arch or native offer; leaving it unchanged. For explicit setup use --install-openrazer on experimental Arch/pacman or named Ubuntu/Debian, Fedora, openSUSE Leap/Tumbleweed, or the manual matching-source route; see docs/release-notes.md#required-openrazer."
    fi
  fi
fi
state="$(active_state)" || die "could not query Naga service state"
PREVIOUS_UNIT_STATE="$(systemctl --user show naga-control.service --property=UnitFileState --value 9>&-)" \
  || die "could not query Naga unit enable state"
case "$PREVIOUS_UNIT_STATE" in
  ""|disabled|enabled|enabled-runtime|static|indirect) ;;
  *) die "Naga unit state is $PREVIOUS_UNIT_STATE; resolve it manually before installation" ;;
esac
case "$state" in
  active|activating|reloading) WAS_ACTIVE=1 ;;
  inactive) ;;
  *) die "Naga service state is $state; resolve it manually before installation" ;;
esac
log "Quit the Naga GUI and release all held mouse controls before proceeding; GUI processes are never killed."
if [ "$WAS_ACTIVE" -eq 1 ]; then
  log "Naga is running: graceful stop temporarily disables remapping; app-only success resumes it. OpenRazer opt-in leaves it stopped."
  if [ "$RESTART_SERVICE" -ne 1 ]; then
    [ -t 0 ] || die "installation canceled: running Naga needs terminal consent or explicit --restart-service"
    answer=""
    read -r -p "Gracefully stop Naga for this upgrade? [y/N] " answer || true
    case "$answer" in [yY]|[yY][eE][sS]) ;; *) die "installation canceled: Naga stop declined" ;; esac
  fi
  systemctl --user stop naga-control.service 9>&- || die "Naga stop failed; installed image was not replaced"
  ensure_stopped || die "Naga stop unfinished/failed; must be inactive before replacement"
  STOPPED=1
fi
# Snapshot user-owned files only, never profiles/configuration or package state.
for path in ".local/bin/naga-control.AppImage" ".local/share/naga-control/installed-tag" ".local/share/naga-control/service-manager" "${USER_FILES[@]}"; do
  if [ -f "$HOME/$path" ]; then
    mkdir -p "$STAGE/previous/$(dirname "$path")"
    cp -p "$HOME/$path" "$STAGE/previous/$path"
  fi
done
# The old probe ran before the consented stop; reverify the stopped snapshot
# before any helper, quarantine, or resume decision. A late change downgrades
# to unverified quarantine, never a trusted rollback or automatic resume.
if [ "$HAD_PREVIOUS_IMAGE" -eq 1 ] && [ "$OLD_VERIFIED" -eq 1 ]; then
  if ! probe_image "$STAGE/previous/.local/bin/naga-control.AppImage" "$OLD_DIGEST"; then
    OLD_VERIFIED=0
    OLD_OBSERVED="$(observe_image "$STAGE/previous/.local/bin/naga-control.AppImage" || true)"
    log "warning: previous image changed after stop (expected $OLD_DIGEST${OLD_OBSERVED:+, observed $OLD_OBSERVED}); treating as unverified quarantine, not a verified rollback"
  fi
fi
if [ "$HAD_PREVIOUS_IMAGE" -eq 1 ] && [ "$OLD_VERIFIED" -eq 0 ]; then
  publish_quarantine || die "could not preserve unverified previous image; Naga stopped; manual recovery required"
fi
if [ "$INSTALL_OPENRAZER" -eq 1 ]; then
  ensure_stopped || die "Naga became active again; quit the GUI before the OpenRazer transaction"
  DEPENDENCIES_STARTED=1
  case "$OPENRAZER_HELPER_KIND" in
    arch|native) ;;
    *) die "unknown helper kind" ;;
  esac
  [ "${#HELPER_BASE_ARGS[@]}" -gt 0 ] || die "missing helper arguments"
  # The foreground helper may inherit this lock; its own privileged/service
  # children close it. Preflight passed before any Naga stop; the actual helper
  # independently repeats its environment gates before the package transaction.
  bash "$OPENRAZER_INSTALLER" "${HELPER_BASE_ARGS[@]}" --install \
    || die "OpenRazer prerequisite step failed; possible partial changes, Naga was not installed/started"
fi
# Prepare integration off to the side; the AppImage never writes live user files.
mkdir -p "$STAGE/integration-home/.local/bin" "$STAGE/udev"
"$STAGE/$ASSET" --install --home "$STAGE/integration-home" --exec-prefix "$APPIMAGE_DST" --udev-dir "$STAGE/udev" 9>&- >/dev/null \
  || die "integration install failed"
printf '#!/usr/bin/env bash\nexec %q gui "$@"\n' "$APPIMAGE_DST" > "$STAGE/integration-home/.local/bin/naga-control"
chmod 755 "$STAGE/integration-home/.local/bin/naga-control"
for path in "${USER_FILES[@]}"; do
  [ -f "$STAGE/integration-home/$path" ] && [ ! -L "$STAGE/integration-home/$path" ] || die "missing/unsafe integration file: $path"
  safe_file "$HOME/$path"
done
safe_file "$APPIMAGE_DST"
safe_file "$STAMP"
ensure_stopped || die "Naga became active again; quit the GUI before replacing the image"
if [ -f "$APPIMAGE_DST" ] && { [ "$INSTALLED_TAG" != "$VERSION" ] || [ "$OLD_DIGEST" != "$NEW_DIGEST" ] || [ -n "${NAGA_CONTROL_FORCE_DOWNLOAD:-}" ] || [ "$OLD_VERIFIED" -eq 0 ]; }; then
  if [ "$OLD_VERIFIED" -eq 1 ]; then
    BACKUP_PENDING="$(mktemp -d "$STATE_DIR/.rollback.XXXXXX")"
    cp -p "$STAGE/previous/.local/bin/naga-control.AppImage" "$BACKUP_PENDING/naga-control.AppImage"
    cp -p "$STAGE/previous/.local/share/naga-control/installed-tag" "$BACKUP_PENDING/installed-tag"
    verify_image "$BACKUP_PENDING/naga-control.AppImage" "$OLD_DIGEST"
    printf '%s  naga-control.AppImage\n' "$OLD_DIGEST" > "$BACKUP_PENDING/image.sha256"
    printf 'naga-control-installer-backup-v1\n' > "$BACKUP_PENDING/installer-backup"
    BACKUP="$STATE_DIR/rollback.${BACKUP_PENDING##*.}"
    [ ! -e "$BACKUP" ] && [ ! -L "$BACKUP" ] || die "rollback destination already exists"
    mv -T "$BACKUP_PENDING" "$BACKUP" || die "could not publish rollback pair"
    BACKUP_PENDING=""
    log "verified rollback pair retained: $BACKUP (not a package/system rollback)"
  elif [ -z "$QUARANTINE" ]; then
    publish_quarantine || die "could not preserve unverified previous image; manual recovery required"
  else
    log "unverified quarantine already retained: $QUARANTINE"
  fi
fi
TOUCHED=1
atomic_copy "$STAGE/$ASSET" "$APPIMAGE_DST" || die "atomic AppImage replacement failed"
printf '%s\n' "$VERSION" > "$STAGE/installed-tag"
atomic_copy "$STAGE/installed-tag" "$STAMP" || die "installed-tag replacement failed"
printf 'systemd\n' > "$STAGE/service-manager"
atomic_copy "$STAGE/service-manager" "$SERVICE_MANAGER_FILE" || die "service-manager replacement failed"
chmod 600 "$SERVICE_MANAGER_FILE" || die "service-manager permissions failed"
for path in "${USER_FILES[@]}"; do
  atomic_copy "$STAGE/integration-home/$path" "$HOME/$path" || die "user integration replacement failed: $path"
done
sudo install -m 644 "$UDEV_SRC" /etc/udev/rules.d/70-naga-control.rules 9>&- || die "udev rule installation failed (system changes are not rolled back)"
UDEV_PENDING=0
if ! sudo udevadm control --reload 9>&-; then
  UDEV_PENDING=1
  log "udev reload failed: app staged, permissions pending; ask your administrator to reload rules and replug the mouse"
fi
# No broad udev trigger: replug only the target mouse after a successful reload.
systemctl --user daemon-reload 9>&- || die "Naga user-unit reload failed"
UNIT_TOUCHED=1
if [ "$INSTALL_OPENRAZER" -eq 1 ] || [ "$UDEV_PENDING" -eq 1 ]; then
  systemctl --user enable naga-control.service 9>&- || die "Naga user-unit enable failed; activation pending"
  ensure_stopped || die "Naga became active while activation must remain deferred; quit the GUI and inspect prerequisites"
  log "installation staged: Naga not started; reboot/re-login for OpenRazer/group changes, or reload/replug for pending udev permissions, then verify before starting Naga"
else
  systemctl --user enable --now naga-control.service 9>&- || die "Naga user-service activation failed"
  [ "$(active_state)" = active ] || die "Naga user-service did not become active"
  log "app installed; Naga user service running (NOT proof of hardware readiness). Replug the mouse if permissions changed."
fi
COMMITTED=1
prune_retention || log "warning: retention cleanup incomplete; older snapshots left for manual inspection"
log "Run '$WRAPPER_DST' to open the GUI after prerequisites are activated."
echo "Verification (not executed by installer; may activate the service):"
echo "busctl --user call org.nagacontrol.Service1 /org/nagacontrol/Service1 org.nagacontrol.Service1 GetSnapshot"
echo "Require status available, then physical F13/F14 DPI and F17 held-ALT down/up checks; installer success does not establish these."
