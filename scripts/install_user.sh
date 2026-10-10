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
      echo "App-only by default; env =1 opts in, =0 hard skips OpenRazer."
      echo "--restart-service consents to a graceful Naga-only stop/resume; quit the GUI and release controls first."
      exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
case "${NAGA_CONTROL_INSTALL_OPENRAZER-}" in
  0) INSTALL_OPENRAZER=0; log "NAGA_CONTROL_INSTALL_OPENRAZER=0: hard skip (including --install-openrazer)" ;;
  1) INSTALL_OPENRAZER=1 ;;
  "") [ "${NAGA_CONTROL_INSTALL_OPENRAZER+x}" != x ] || die "NAGA_CONTROL_INSTALL_OPENRAZER must be 0, 1, or unset" ;;
  *) die "NAGA_CONTROL_INSTALL_OPENRAZER must be 0, 1, or unset" ;;
esac
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
  OPENRAZER_INSTALLER="$SCRIPT_DIR/install_openrazer.sh"
  if [ ! -f "$OPENRAZER_INSTALLER" ]; then
    OPENRAZER_INSTALLER="$STAGE/install_openrazer.sh"
    curl -fsSL -o "$OPENRAZER_INSTALLER" "https://raw.githubusercontent.com/$REPO/$VERSION/scripts/install_openrazer.sh" \
      || die "could not download install_openrazer.sh for $VERSION"
  fi
  [ -s "$OPENRAZER_INSTALLER" ] || die "empty OpenRazer helper"
  log "checking optional OpenRazer install prerequisites before Naga stop consent"
  bash "$OPENRAZER_INSTALLER" --version "$VERSION" --preflight 9>&- \
    || die "OpenRazer prerequisite preflight failed; Naga unchanged; opt-in requires a helper supporting --preflight (no legacy fallback)"
else
  log "app-only install: OpenRazer packages, group, and daemon are unchanged"
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
  # The foreground helper may inherit this lock; its own privileged/service
  # children close it. Preflight passed before any Naga stop; the actual helper
  # independently repeats its environment gates before the package transaction.
  bash "$OPENRAZER_INSTALLER" --version "$VERSION" --install \
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
