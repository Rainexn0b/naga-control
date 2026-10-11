#!/usr/bin/env bash
# Verified, serialized desktop-user AppImage installation. No hardware probes.
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
    -h|--help)
      echo "usage: install_user.sh [--version <tag>] [--install-openrazer] [--restart-service]"
      echo "App-only by default; offers consented OpenRazer setup if absent on eligible Arch or named Ubuntu/Debian, Fedora, openSUSE Leap/Tumbleweed, existing/manual/unknown unchanged; env =1 opts in, =0 hard skips OpenRazer."
      echo "--install-openrazer requests explicit first-install setup (reviewed reinstall/partial inventory only on Arch; existing, partial, manual, or unknown native backends need manual matching-cohort migration) and nonTTY handling."
      echo "--restart-service consents to a graceful Naga-only stop/resume; quit the GUI and release controls first."
      exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
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
for tool in id uname curl systemctl busctl sudo install udevadm sha256sum flock mktemp mkdir rm rmdir dirname cp mv chmod cmp grep stat; do
  command -v "$tool" >/dev/null || die "$tool is required; see docs/troubleshooting.md#installer-prerequisites (no automatic package installation)"
done
[ "$(id -u)" -ne 0 ] || die "run as your desktop user, not root"
[ "$(uname -s)" = Linux ] && [ "$(uname -m)" = x86_64 ] || die "only Linux x86_64 has this installer artifact"
[ -d "$HOME" ] && [ -w "$HOME" ] && [ -x "$HOME" ] || die "HOME must be an existing writable desktop-user directory"
safe_path "$STATE_DIR"
for path in "$APPIMAGE_DST" "$STAMP" "$STATE_DIR/install.lock"; do safe_file "$path"; done
for path in "${USER_FILES[@]}"; do safe_file "$HOME/$path"; done
systemctl --user show --property=Version --value >/dev/null || die "user systemd unavailable; log into a normal desktop session (install systemd user support)"
busctl --user status >/dev/null || die "session D-Bus unavailable; log into a desktop session with dbus-user-session/dbus"
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
active_state() { systemctl --user show naga-control.service --property=ActiveState --value 9>&-; }
ensure_stopped() {
  local state
  state="$(active_state)" || return 1
  [ "$state" = inactive ]
}
restore() {
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
  for path in ".local/bin/naga-control.AppImage" ".local/share/naga-control/installed-tag" "${USER_FILES[@]}"; do
    if [ -f "$STAGE/previous/$path" ]; then
      atomic_copy "$STAGE/previous/$path" "$HOME/$path" || failed=1
    else
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
        if ! ensure_stopped; then
          systemctl --user stop naga-control.service 9>&- && ensure_stopped \
            || echo "RESTORATION FAILED: Naga could not be kept inactive after the prerequisite failure" >&2
        fi
        if ensure_stopped; then
          echo "error: Naga remains stopped; OpenRazer step failed/was interrupted, possible partial package changes; inspect inventory before reboot/re-login" >&2
        else
          echo "error: Naga is not safely stopped; OpenRazer may have partial changes; stop it manually and inspect inventory before activation" >&2
        fi
      elif [ "$WAS_ACTIVE" -eq 1 ]; then
        log "previous app/integration files unchanged; resuming the previous Naga service"
        systemctl --user start naga-control.service 9>&- && [ "$(active_state)" = active ] \
          || echo "RESTORATION FAILED: previous service could not resume" >&2
      fi
    fi
    echo "error: installation not completed" >&2
  fi
  [ "${#SIBLINGS[@]}" -eq 0 ] || rm -f -- "${SIBLINGS[@]}" || true
  [ -z "$BACKUP_PENDING" ] || rm -rf -- "$BACKUP_PENDING" || true
  [ -z "$QUARANTINE_PENDING" ] || rm -rf -- "$QUARANTINE_PENDING" || true
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
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/naga-install.XXXXXX")"
# FD 9 stays with the installer and its foreground prerequisite helper only.
# AppImage, sudo and systemctl children close their copies before activation.
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
if [ "$INSTALL_OPENRAZER" -eq 1 ]; then
  offer_parse_identity
  if offer_arch_eligible; then
    OPENRAZER_HELPER_KIND="arch"
    ensure_arch_helper
    HELPER_BASE_ARGS=(--version "$VERSION")
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
for path in ".local/bin/naga-control.AppImage" ".local/share/naga-control/installed-tag" "${USER_FILES[@]}"; do
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
