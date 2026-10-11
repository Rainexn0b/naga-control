#!/usr/bin/env bash

# Standalone native OpenRazer setup helper with local builds. No hardware access.
set -euo pipefail
umask 077
HOME="${HOME%/}"

REPO="Rainexn0b/naga-control"
OPENRAZER_REPO="Rainexn0b/openrazer"
OPENRAZER_COMMIT="26b0eeb5ed70d638fa3528851adcd5e58369a7f5"
PACKAGE_VERSION="3.12.1.pr2904.fix2-1"
ROLES=(openrazer-driver-dkms-local openrazer-daemon-local python-openrazer-local)
FAMILY=""
VERSION=""
CODE_REF=""
CHECK=0
PREFLIGHT=0
INSTALL=0
YES=0
ADD_GROUP=0

die() { echo "error: $*" >&2; exit 1; }
log() { echo "==> $*"; }
usage() {
  cat <<'EOF'
usage: install_openrazer_native.sh --family debian|fedora|opensuse [--version <tag>]
       [--code-ref <ref>] [--check | --preflight | --install | --yes]
       [--add-openrazer-group]
Default/--check: read-only installed inventory, no network or hardware calls.
--preflight: read-only local eligibility and prerequisite plan, no downloads,
tmp, lock, prompts, writes or package changes; overrides install flags.
--install: build locally and install the exact three native packages in one
interactive manager transaction; confirm the summary first.
--yes: opt in and skip ONLY the summary confirmation, NOT prerequisite or
package-manager or group prompts.
--add-openrazer-group: separate consent to add the actual id -un user.
NAGA_CONTROL_INSTALL_OPENRAZER=1 opts in (summary still required); =0 is a
hard skip even with flags. Unset is read-only; other values are errors.
Only named Ubuntu/Debian, Fedora, openSUSE Leap/Tumbleweed with system
Python 3.10+ are eligible. Other IDs and derivatives have no automated
helper on supported automatic routes. See docs/release-notes.md before replacing anything.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --family) [ "$#" -ge 2 ] || die "--family requires debian|fedora|opensuse"; FAMILY="$2"; shift 2 ;;
    --version) [ "$#" -ge 2 ] || die "--version requires a tag"; VERSION="$2"; shift 2 ;;
    --code-ref) [ "$#" -ge 2 ] || die "--code-ref requires a ref"; CODE_REF="$2"; shift 2 ;;
    --install) INSTALL=1; shift ;;
    --yes) INSTALL=1; YES=1; shift ;;
    --check) CHECK=1; shift ;;
    --preflight) PREFLIGHT=1; shift ;;
    --add-openrazer-group) ADD_GROUP=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

case "${NAGA_CONTROL_INSTALL_OPENRAZER-}" in
  0) log "NAGA_CONTROL_INSTALL_OPENRAZER=0: hard skip (including install flags)"; exit 0 ;;
  1) INSTALL=1 ;;
  "") [ "${NAGA_CONTROL_INSTALL_OPENRAZER+x}" != x ] || die "NAGA_CONTROL_INSTALL_OPENRAZER must be 0, 1, or unset" ;;
  *) die "NAGA_CONTROL_INSTALL_OPENRAZER must be 0, 1, or unset" ;;
esac

case "$FAMILY" in
  debian|fedora|opensuse) ;;
  *) die "--family must be debian|fedora|opensuse" ;;
esac

[ -z "$VERSION" ] || [[ "$VERSION" =~ ^[a-zA-Z0-9][a-zA-Z0-9._+-]*$ ]] || die "invalid release tag"
if [ -z "$CODE_REF" ]; then
  CODE_REF="${NAGA_CONTROL_BOOTSTRAP_REF:-main}"
fi
[[ "$CODE_REF" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] || die "invalid code ref"
case "$CODE_REF" in
  *..*|/*|*/|*//*) die "invalid code ref" ;;
esac
if [[ "$CODE_REF" =~ [[:cntrl:]] ]]; then
  die "invalid code ref"
fi

OS_ID="UNKNOWN"
OS_LIKE=""
OS_VERSION=""
OS_STATUS="unknown"

parse_identity() {
  local LC_ALL=C
  local path="" data="" line="" raw="" key="" quote=""
  local seen_id=0 seen_like=0 seen_ver=0 newline=0
  OS_ID="UNKNOWN"
  OS_LIKE=""
  OS_VERSION=""
  OS_STATUS="unknown"
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
  seen_id=0
  seen_like=0
  seen_ver=0
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
      OS_ID="UNKNOWN"; OS_LIKE=""; OS_VERSION=""; OS_STATUS="unknown"; return 0
    fi
    if [ "$newline" -eq 1 ]; then
      line="${line%$'\r'}"
    fi
    if [[ "$line" =~ [[:cntrl:]] ]]; then
      OS_ID="UNKNOWN"; OS_LIKE=""; OS_VERSION=""; OS_STATUS="unknown"; return 0
    fi
    case "$line" in ""|\#*) continue ;; esac
    if [[ "$line" =~ ^\ *(ID|ID_LIKE|VERSION_ID)([^A-Za-z0-9_]|$) ]]; then
      [[ "$line" =~ ^(ID|ID_LIKE|VERSION_ID)= ]] || { OS_ID="UNKNOWN"; OS_LIKE=""; OS_VERSION=""; OS_STATUS="unknown"; return 0; }
      key="${BASH_REMATCH[1]}"
      raw="${line#*=}"
      if [ "$key" = "ID" ]; then
        [ "$seen_id" -eq 0 ] || { OS_ID="UNKNOWN"; OS_LIKE=""; OS_VERSION=""; OS_STATUS="unknown"; return 0; }
        seen_id=1
      elif [ "$key" = "ID_LIKE" ]; then
        [ "$seen_like" -eq 0 ] || { OS_ID="UNKNOWN"; OS_LIKE=""; OS_VERSION=""; OS_STATUS="unknown"; return 0; }
        seen_like=1
      else
        [ "$seen_ver" -eq 0 ] || { OS_ID="UNKNOWN"; OS_LIKE=""; OS_VERSION=""; OS_STATUS="unknown"; return 0; }
        seen_ver=1
      fi
      case "$raw" in
        \"*\"|\'*\' )
          quote="${raw:0:1}"
          [ "${#raw}" -ge 2 ] || { OS_ID="UNKNOWN"; OS_LIKE=""; OS_VERSION=""; OS_STATUS="unknown"; return 0; }
          [ "${raw: -1}" = "$quote" ] || { OS_ID="UNKNOWN"; OS_LIKE=""; OS_VERSION=""; OS_STATUS="unknown"; return 0; }
          raw="${raw:1:${#raw}-2}"
          ;;
      esac
      if [ "$key" = "ID" ]; then
        [[ "$raw" =~ ^[a-z0-9._-]+$ ]] || { OS_ID="UNKNOWN"; OS_LIKE=""; OS_VERSION=""; OS_STATUS="unknown"; return 0; }
        OS_ID="$raw"
      elif [ "$key" = "ID_LIKE" ]; then
        [[ "$raw" =~ ^[a-z0-9._-]+(\ +[a-z0-9._-]+)*$ ]] || { OS_ID="UNKNOWN"; OS_LIKE=""; OS_VERSION=""; OS_STATUS="unknown"; return 0; }
        OS_LIKE="$raw"
      else
        [[ "$raw" =~ ^[A-Za-z0-9._+-]+$ ]] || { OS_ID="UNKNOWN"; OS_LIKE=""; OS_VERSION=""; OS_STATUS="unknown"; return 0; }
        OS_VERSION="$raw"
      fi
    fi
  done
  [ "$seen_id" -eq 1 ] || { OS_ID="UNKNOWN"; OS_LIKE=""; OS_VERSION=""; OS_STATUS="unknown"; return 0; }
  OS_STATUS="parsed"
}

family_expected_id() {
  case "$FAMILY" in
    debian) case "$OS_ID" in ubuntu|debian) return 0 ;; *) return 1 ;; esac ;;
    fedora) case "$OS_ID" in fedora) return 0 ;; *) return 1 ;; esac ;;
    opensuse) case "$OS_ID" in opensuse-leap|opensuse-tumbleweed) return 0 ;; *) return 1 ;; esac ;;
  esac
  return 1
}

family_managers_available() {
  case "$FAMILY" in
    debian) command -v apt-get >/dev/null 2>&1 && command -v dpkg-query >/dev/null 2>&1 ;;
    fedora) command -v dnf >/dev/null 2>&1 && command -v rpm >/dev/null 2>&1 ;;
    opensuse) command -v zypper >/dev/null 2>&1 && command -v rpm >/dev/null 2>&1 ;;
  esac
}

inventory() {
  local LC_ALL=C
  local output="" line="" name="" ver="" status="" pkg="" low=""
  local found=0 query_ok=0
  local py_out="" py_rc=0 py_p="" py_c="" py_d=""
  parse_identity
  if [ "$FAMILY" = "debian" ]; then
    if command -v dpkg-query >/dev/null 2>&1; then
      if output="$(dpkg-query -W -f='${Status} ${Package} ${Version}\n' 2>/dev/null | /usr/bin/python3 -I -B -c 'import sys; data=sys.stdin.buffer.read(1048577); sys.exit(1) if len(data)>1048576 or b"\x00" in data or any(b!=10 and not 32<=b<=126 for b in data) else sys.stdout.buffer.write(data)')"; then
        query_ok=1
        if [ -n "$output" ]; then
          while IFS= read -r line; do
            [ -n "$line" ] || continue
            if [[ "$line" =~ [[:cntrl:]] ]]; then
              query_ok=0
              break
            fi
            # Strict dpkg row: 3-word Status + Package + Version (5 fields).
            # shellcheck disable=SC2206
            read -r -a fields <<< "$line" || { query_ok=0; break; }
            if [ "${#fields[@]}" -ne 5 ]; then
              query_ok=0
              break
            fi
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
            case "$low" in
              *openrazer*|*razer-*) found=1; break ;;
            esac
          done <<< "$output"
        fi
      else
        log "installed package cohort unknown (query failed)"
        query_ok=0
      fi
    else
      log "dpkg-query unavailable: installed package cohort unknown"
      query_ok=0
    fi
  else
    if command -v rpm >/dev/null 2>&1; then
      if output="$(rpm -qa --queryformat '%{NAME} %{VERSION}-%{RELEASE}\n' 2>/dev/null | /usr/bin/python3 -I -B -c 'import sys; data=sys.stdin.buffer.read(1048577); sys.exit(1) if len(data)>1048576 or b"\x00" in data or any(b!=10 and not 32<=b<=126 for b in data) else sys.stdout.buffer.write(data)')"; then
        query_ok=1
        if [ -n "$output" ]; then
          while IFS= read -r line; do
            [ -n "$line" ] || continue
            if [[ "$line" =~ [[:cntrl:]] ]]; then
              query_ok=0
              break
            fi
            case "$line" in *" "* ) ;; *) query_ok=0; break ;; esac
            name="${line%% *}"
            ver="${line#* }"
            case "$ver" in *" "* ) query_ok=0; break ;; esac
            [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._+-]*$ ]] || { query_ok=0; break; }
            [[ "$ver" =~ ^[A-Za-z0-9][A-Za-z0-9._+:~+-]*$ ]] || { query_ok=0; break; }
            low="${name,,}"
            case "$low" in
              *openrazer*|*razer-*) found=1; break ;;
            esac
          done <<< "$output"
        fi
      else
        log "installed package cohort unknown (query failed)"
        query_ok=0
      fi
    else
      log "rpm unavailable: installed package cohort unknown"
      query_ok=0
    fi
  fi
  if [ "$found" -eq 1 ]; then
    log "UNVERIFIED: existing OpenRazer packages detected; native first install refuses replacement"
  elif [ "$query_ok" -ne 1 ]; then
    log "UNVERIFIED: package inventory unknown; native first install refuses without a clean read"
  fi
  if [ ! -x "/usr/bin/python3" ]; then
    log "Host import discoverability: unknown (/usr/bin/python3 unavailable)"
    return 1
  fi
  py_out=""
  py_rc=0
  py_out="$(/usr/bin/python3 -I -B -c 'from importlib.machinery import PathFinder; import sys; p = PathFinder.find_spec("openrazer"); c = PathFinder.find_spec("openrazer.client", p.submodule_search_locations) if p else None; d = PathFinder.find_spec("openrazer_daemon"); print(f"OPENRAZER-PROBE p={p is not None} client={c is not None} daemon={d is not None}"); sys.exit(0 if (p is None and d is None) else 1)' 2>/dev/null | /usr/bin/python3 -I -B -c 'import sys; data=sys.stdin.buffer.read(1048577); sys.exit(1) if len(data)>1048576 or b"\x00" in data or any(b!=10 and not 32<=b<=126 for b in data) else sys.stdout.buffer.write(data)')" || py_rc=$?
  if [[ ! "$py_out" =~ ^OPENRAZER-PROBE\ p=(True|False)\ client=(True|False)\ daemon=(True|False)$ ]]; then
    log "Host import discoverability: unknown (malformed Python probe)"
    log "UNVERIFIED: package inventory unknown; native first install refuses without a clean read"
    return 1
  fi
  log "Host import discoverability: $py_out"
  # Re-parse all three fields from the single validated marker.
  [[ "$py_out" =~ ^OPENRAZER-PROBE\ p=(True|False)\ client=(True|False)\ daemon=(True|False)$ ]]
  py_p="${BASH_REMATCH[1]}"
  py_c="${BASH_REMATCH[2]}"
  py_d="${BASH_REMATCH[3]}"
  if [ "$py_p" = "True" ] || [ "$py_c" = "True" ] || [ "$py_d" = "True" ]; then
    found=1
  fi
  if [ "$py_rc" -ne 0 ] && [ "$found" -ne 1 ]; then
    log "Host import discoverability: unknown (Python probe failed)"
    log "UNVERIFIED: package inventory unknown; native first install refuses without a clean read"
    return 1
  fi
  if command -v openrazer-daemon >/dev/null 2>&1; then
    log "openrazer-daemon command present: manual installation preserved"
    found=1
  fi
  if [ "$found" -eq 1 ]; then
    log "UNVERIFIED: manual or packaged OpenRazer present; follow manual matching-cohort migration"
    return 1
  fi
  if [ "$query_ok" -ne 1 ]; then
    return 1
  fi
  log "ABSENT: no OpenRazer packages, commands, or host imports detected"
  return 0
}

find_build_tree() {
  local kernel="$1" candidate=""
  for candidate in "/usr/lib/modules/$kernel/build" "/lib/modules/$kernel/build"; do
    if [ -d "$candidate" ] && [ -r "$candidate/Makefile" ] && [ -r "$candidate/.config" ]; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

preflight() {
  local LC_ALL=C
  local executable kernel="" tree="" evr=""
  command -v id >/dev/null || die "id is required"
  [ "$(id -u)" -ne 0 ] || die "run as your desktop user, not root"
  [ -z "$VERSION" ] || [[ "$VERSION" =~ ^[a-zA-Z0-9][a-zA-Z0-9._+-]*$ ]] || die "invalid release tag"
  [ -x "/usr/bin/python3" ] || die "/usr/bin/python3 is required (system interpreter, not a virtualenv alias)"
  for executable in id uname curl sha256sum stat flock mktemp rm mkdir dirname sudo systemctl busctl head grep chmod cat ls; do
    command -v "$executable" >/dev/null || die "$executable is required (native $FAMILY path only)"
  done
  [ "$(uname -s)" = Linux ] && [ "$(uname -m)" = x86_64 ] || die "this native installer requires Linux x86_64"
  "/usr/bin/python3" -I -B -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
    || die "host Python 3.10+ is required by the native builder (system interpreter, no replacement)"
  parse_identity
  [ "$OS_STATUS" = "parsed" ] || die "unsupported host: /etc/os-release could not be parsed as data"
  family_expected_id || die "unsupported host $OS_ID for --family $FAMILY (named Ubuntu/Debian, Fedora, openSUSE Leap/Tumbleweed only; derivatives unsupported)"
  family_managers_available || die "native manager capability missing for --family $FAMILY (need apt-get+dpkg-query, dnf+rpm, or zypper+rpm)"
  if [ -n "$OS_VERSION" ]; then
    log "Host $OS_ID $OS_VERSION with --family $FAMILY; unknown versions are conditional, not certified (ID_LIKE ${OS_LIKE:-none})"
  else
    log "Host $OS_ID with --family $FAMILY; version unknown, conditional support only (ID_LIKE ${OS_LIKE:-none})"
  fi
  systemctl --user show --property=Version --value 9>&- >/dev/null \
    || die "user systemd unavailable; log into a normal desktop session before opting in"
  busctl --user status 9>&- >/dev/null \
    || die "session D-Bus unavailable; log into a desktop session with dbus-user-session/dbus before opting in"
  kernel="$(uname -r)"
  case "$kernel" in
    ""|*..*|*/*|*" "*) die "unsafe kernel release string" ;;
  esac
  [[ "$kernel" =~ ^[A-Za-z0-9._+-]+$ ]] || die "unsafe kernel release string"
  if tree="$(find_build_tree "$kernel")"; then
    log "Active-kernel build tree present: $tree"
    if grep -Eq '^CONFIG_CC_IS_CLANG=y$' "$tree/.config"; then
      log "Clang kernel detected: plan clang llvm lld until install consent"
    fi
  else
    log "Active-kernel build tree missing (planned until install consent): /usr/lib/modules/$kernel/build"
    if [ "$FAMILY" = "opensuse" ]; then
      case "$kernel" in
        *-default) ;;
        *) die "SUSE active-kernel flavor unknown for $kernel with missing headers; manual headers required, no guess" ;;
      esac
      evr="$(rpm -q --whatprovides "kernel-uname-r = $kernel" --queryformat '%{VERSION}-%{RELEASE}\n' 2>/dev/null)" \
        || die "SUSE active-kernel flavor unknown for $kernel with missing headers; manual headers required, no guess"
      [[ "$evr" =~ ^[A-Za-z0-9._+-]+$ ]] || die "SUSE active-kernel flavor unknown for $kernel with missing headers; manual headers required, no guess"
      log "SUSE exact headers planned: kernel-devel=$evr kernel-default-devel=$evr"
    fi
  fi
  log "Prerequisite plan for $FAMILY (no changes made by --preflight):"
  case "$FAMILY" in
    debian)
      log "sudo apt-get install dkms udev python3-dbus python3-gi python3-pyudev python3-setproctitle python3-daemonize gir1.2-glib-2.0 libnotify-bin xautomation dbus-user-session python3-numpy git make gcc python3-setuptools dpkg-dev (+ linux-headers-$kernel only if build tree missing; + clang llvm lld if CONFIG_CC_IS_CLANG=y)"
      ;;
    fedora)
      log "sudo dnf install python3-dbus python3-gobject python3-setproctitle python3-pyudev python3-daemonize python3-numpy xautomation dkms make gcc git python3-setuptools rpm-build rpm shadow-utils (+ kernel-devel-$kernel only if build tree missing; + clang llvm lld if CONFIG_CC_IS_CLANG=y)"
      ;;
    opensuse)
      log "sudo zypper install dbus-1-python3 python3-gobject python3-setproctitle python3-pyudev python3-daemonize python3-numpy xautomation dkms make gcc git python3-setuptools rpm-build rpm shadow typelib(Gdk) = 3.0 (+ kernel-devel/kernel-default-devel exact EVR only if build tree missing)"
      ;;
  esac
  for executable in git make cc gcc dpkg-deb rpmbuild rpm2cpio dkms clang ld.lld llvm-ar llvm-nm llvm-objcopy llvm-objdump llvm-readelf llvm-strip; do
    if command -v "$executable" >/dev/null 2>&1; then
      log "build tool present: $executable"
    else
      log "build tool missing (planned until install consent): $executable"
    fi
  done
  log "Missing headers consent installs only the matching active-kernel package; no kernel upgrade, repo addition, SecureBoot change, or key enrollment"
  log "Read-only native preflight passed; no network, lock/state writes, prompts, package changes or unit configuration"
}

if [ "$PREFLIGHT" -eq 1 ]; then
  preflight
  exit 0
fi

if inventory; then
  INVENTORY_ABSENT=1
else
  INVENTORY_ABSENT=0
fi
[ "$INSTALL" -eq 1 ] && [ "$CHECK" -ne 1 ] || exit 0

if [ "$INVENTORY_ABSENT" -ne 1 ]; then
  die "native first install refused: existing, partial, manual, or unknown OpenRazer detected; follow manual matching-cohort migration or the Arch-specific helper only on compatible Arch hosts; no silent replacement"
fi
preflight

log "Native first install summary: source $OPENRAZER_COMMIT cohort $PACKAGE_VERSION family $FAMILY"
log "Local unsigned native packages built from a pinned Git checkout; source verification is HTTPS GitHub plus exact SHA, not SLSA or signed packages"
log "Build tools and headers install only with your separate prerequisite consent; managers keep their own prompts (no -y/--noconfirm/--non-interactive)"
log "Group openrazer is never automatic; daemon enable is deferred without start; reboot/re-login required"
log "Supported only on named Ubuntu/Debian, Fedora, openSUSE Leap/Tumbleweed with system Python 3.10+; other IDs unsupported"
log "Stop Naga and other OpenRazer clients before proceeding; save previous package list"
kernel="$(uname -r)"
case "$kernel" in
  ""|*..*|*/*|*" "*) die "unsafe kernel release string" ;;
esac
[[ "$kernel" =~ ^[A-Za-z0-9._+-]+$ ]] || die "unsafe kernel release string"
HAVE_TREE=0
TREE_PATH=""
if TREE_PATH="$(find_build_tree "$kernel")"; then
  HAVE_TREE=1
fi
CLANG_NEED=0
if [ "$HAVE_TREE" -eq 1 ] && grep -Eq '^CONFIG_CC_IS_CLANG=y$' "$TREE_PATH/.config"; then
  CLANG_NEED=1
fi
EVR=""
if [ "$FAMILY" = "opensuse" ] && [ "$HAVE_TREE" -eq 0 ]; then
  case "$kernel" in
    *-default) ;;
    *) die "SUSE active-kernel flavor unknown for $kernel with missing headers; manual headers required, no guess" ;;
  esac
  evr="$(rpm -q --whatprovides "kernel-uname-r = $kernel" --queryformat '%{VERSION}-%{RELEASE}\n' 2>/dev/null)" \
    || die "SUSE active-kernel flavor unknown for $kernel with missing headers; manual headers required, no guess"
  [[ "$evr" =~ ^[A-Za-z0-9._+-]+$ ]] || die "SUSE active-kernel flavor unknown for $kernel with missing headers; manual headers required, no guess"
  EVR="$evr"
fi
PREREQ=()
case "$FAMILY" in
  debian)
    PREREQ=(dkms udev python3-dbus python3-gi python3-pyudev python3-setproctitle python3-daemonize gir1.2-glib-2.0 libnotify-bin xautomation dbus-user-session python3-numpy git make gcc python3-setuptools dpkg-dev)
    if [ "$HAVE_TREE" -eq 0 ]; then
      PREREQ+=("linux-headers-$kernel")
    fi
    if [ "$CLANG_NEED" -eq 1 ]; then
      PREREQ+=(clang llvm lld)
    fi
    ;;
  fedora)
    PREREQ=(python3-dbus python3-gobject python3-setproctitle python3-pyudev python3-daemonize python3-numpy xautomation dkms make gcc git python3-setuptools rpm-build rpm shadow-utils)
    if [ "$HAVE_TREE" -eq 0 ]; then
      PREREQ+=("kernel-devel-$kernel")
    fi
    if [ "$CLANG_NEED" -eq 1 ]; then
      PREREQ+=(clang llvm lld)
    fi
    ;;
  opensuse)
    PREREQ=(dbus-1-python3 python3-gobject python3-setproctitle python3-pyudev python3-daemonize python3-numpy xautomation dkms make gcc git python3-setuptools rpm-build rpm shadow "typelib(Gdk) = 3.0")
    if [ "$HAVE_TREE" -eq 0 ]; then
      PREREQ+=("kernel-devel=$EVR" "kernel-default-devel=$EVR")
    fi
    if [ "$CLANG_NEED" -eq 1 ]; then
      PREREQ+=(clang llvm lld)
    fi
    ;;
esac
preview=""
case "$FAMILY" in
  debian) preview="sudo apt-get install" ;;
  fedora) preview="sudo dnf install" ;;
  opensuse) preview="sudo zypper install" ;;
esac
for item in "${PREREQ[@]}"; do
  preview+=" $(printf '%q' "$item")"
done
log "Preview: $preview"
log "Preview: local build then sudo install of exactly openrazer-driver-dkms-local openrazer-daemon-local python-openrazer-local (zypper uses --allow-unsigned-rpm only for these verified local files)"
if [ "$YES" -ne 1 ]; then
  [ -t 0 ] || die "summary confirmation requires a terminal; --yes skips only this confirmation, never manager or group prompts"
  answer=""
  read -r -p "Build locally and install the native cohort (managers keep their prompts)? [y/N] " answer || true
  case "$answer" in
    [yY]|[yY][eE][sS]) ;;
    *) die "Native install declined; nothing installed" ;;
  esac
fi
[ -t 0 ] || die "prerequisite confirmation requires a terminal; nothing installed"
answer=""
read -r -p "Install the previewed prerequisites (managers keep their prompts)? [y/N] " answer || true
case "$answer" in
  [yY]|[yY][eE][sS]) ;;
  *) die "Prerequisites declined; nothing installed" ;;
esac

lock_dir="$HOME/.local/share/naga-control"
path="$lock_dir/install.lock"
while :; do
  [ ! -L "$path" ] || die "symlink installer lock destination/ancestor: $path"
  [ "$path" != "$HOME" ] || break
  [ "$path" != / ] || die "installer lock must be inside HOME"
  path="$(dirname "$path")"
done
mkdir -p "$lock_dir"
if ! { [ -O "$lock_dir" ] && { [ ! -e "$lock_dir/install.lock" ] || { [ -f "$lock_dir/install.lock" ] && [ -O "$lock_dir/install.lock" ]; }; }; }; then
  die "installer lock directory/file must belong to the desktop user"
fi
lock_mode="$(stat -Lc '%a' "$lock_dir")" || die "could not inspect installer lock directory permissions"
if ! { [[ "$lock_mode" =~ ^[0-7]{3,4}$ ]] && (( (8#$lock_mode & 0022) == 0 )); }; then
  die "installer lock directory must not be group/other writable; fix its permissions manually"
fi
if [ ! -e "/proc/$$/fd/9" ] || [ "$(stat -Lc '%d:%i' "/proc/$$/fd/9")" != "$(stat -Lc '%d:%i' "$lock_dir/install.lock")" ]; then
  exec 9>>"$lock_dir/install.lock"
fi
flock -n 9 || die "another Naga installer is running; wait for it to finish"

tmp="$(mktemp -d "${TMPDIR:-/tmp}/naga-native.XXXXXX")"
DID_SUDO=0
cleanup() {
  local status=$?
  trap - EXIT HUP INT TERM
  if [ -n "${tmp:-}" ] && [ -O "$tmp" ]; then
    rm -rf "$tmp"
  fi
  if [ "$status" -ne 0 ] && [ "${DID_SUDO:-0}" -eq 1 ]; then
    echo "error: install failed after prerequisite/package changes; possible partial prereq/pkg state; activation pending, profiles unchanged" >&2
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

DID_SUDO=1
case "$FAMILY" in
  debian)
    sudo apt-get install "${PREREQ[@]}" 9>&- \
      || die "prerequisite install failed; possible partial prereq changes; no guessed external repo; inspect stock-repo DKMS availability"
    ;;
  fedora)
    sudo dnf install "${PREREQ[@]}" 9>&- \
      || die "prerequisite install failed; possible partial prereq changes; no guessed external repo; inspect stock-repo DKMS availability"
    ;;
  opensuse)
    sudo zypper install "${PREREQ[@]}" 9>&- \
      || die "prerequisite install failed; possible partial prereq changes; no guessed external repo; inspect stock-repo DKMS availability"
    ;;
esac

TREE_AFTER=""
if ! TREE_AFTER="$(find_build_tree "$kernel")"; then
  die "active-kernel headers/build tree and .config missing for $kernel after consented prerequisites; install matching headers manually"
fi
if grep -Eq '^CONFIG_CC_IS_CLANG=y$' "$TREE_AFTER/.config"; then
  for executable in cc make dkms clang ld.lld llvm-ar llvm-nm llvm-objcopy llvm-objdump llvm-readelf llvm-strip; do
    command -v "$executable" >/dev/null || die "$executable is required for this Clang kernel after consented prerequisites; install clang llvm lld manually"
  done
else
  for executable in cc make dkms; do
    command -v "$executable" >/dev/null || die "$executable is required after consented prerequisites"
  done
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODE_ROOT=""
LOCAL_OK=1
for f in "$SCRIPT_DIR/../buildpython/__init__.py" "$SCRIPT_DIR/../buildpython/openrazer_native/__init__.py" "$SCRIPT_DIR/../buildpython/openrazer_native/__main__.py" "$SCRIPT_DIR/../buildpython/openrazer_packages/pin.py" "$SCRIPT_DIR/../buildpython/openrazer_packages/pin.conf" "$SCRIPT_DIR/../buildpython/openrazer_packages/dkms-make"; do
  if [ ! -f "$f" ] || [ -L "$f" ]; then
    LOCAL_OK=0
    break
  fi
done
if [ ! -d "$SCRIPT_DIR/../buildpython/openrazer_native" ] || [ -L "$SCRIPT_DIR/../buildpython/openrazer_native" ]; then
  LOCAL_OK=0
fi
if [ "$LOCAL_OK" -eq 1 ]; then
  CODE_ROOT="$SCRIPT_DIR/.."
else
  curl -fsSL -H "Accept: application/vnd.github.sha" -o "$tmp/naga-sha" "https://api.github.com/repos/$REPO/commits/$CODE_REF" \
    || die "could not resolve Naga code ref $CODE_REF; no packages built"
  "/usr/bin/python3" -I -B - "$tmp/naga-sha" <<'PY' || die "invalid Naga code ref data; no packages built"
import pathlib
import re
import sys
text = pathlib.Path(sys.argv[1]).read_text(encoding="ascii")
if not re.fullmatch(r"[0-9a-f]{40}\n?", text):
    print("error: invalid Naga code SHA", file=sys.stderr)
    sys.exit(1)
PY
  NAGA_SHA="$(cat "$tmp/naga-sha")"
  NAGA_SHA="${NAGA_SHA%$'\n'}"
  [[ "$NAGA_SHA" =~ ^[0-9a-f]{40}$ ]] || die "invalid Naga code SHA"
  curl -fsSL -o "$tmp/naga.tar.gz" "https://codeload.github.com/$REPO/tar.gz/$NAGA_SHA" \
    || die "could not fetch Naga source $NAGA_SHA; no packages built"
  CODE_ROOT="$tmp/code-root"
  mkdir -p "$CODE_ROOT"
  "/usr/bin/python3" -I -B - "$tmp/naga.tar.gz" "$CODE_ROOT" "$NAGA_SHA" <<'PY' || die "invalid Naga source archive; no packages built"
import os
import posixpath
import re
import sys
import tarfile
archive, dest, sha = sys.argv[1:]
expected_root = "naga-control-" + sha
if not re.fullmatch(r"[0-9a-f]{40}", sha):
    raise ValueError("bad sha")
try:
    size = os.path.getsize(archive)
except OSError:
    raise ValueError("archive size")
if size == 0 or size > 20 * 1024 * 1024:
    raise ValueError("archive byte bound")
allowed_native = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*\.py")
seen = set()
selected = []
tops = set()
with tarfile.open(archive, "r:gz") as tar:
    members = tar.getmembers()
    if not members or len(members) > 2000:
        raise ValueError("archive entry count")
    total = 0
    for member in members:
        total += member.size
        if total > 100 * 1024 * 1024:
            raise ValueError("archive expanded bound")
        if member.size < 0 or member.size > 5 * 1024 * 1024:
            raise ValueError("entry size")
        raw = member.name
        if not raw or raw.startswith("/") or "\\" in raw:
            raise ValueError("unsafe member")
        if any(ord(c) < 32 or ord(c) == 127 for c in raw):
            raise ValueError("control member")
        # Normalize: split, drop empty/dot, reject dotdot.
        parts = raw.split("/")
        norm = []
        for part in parts:
            if part in ("", "."):
                continue
            if part == "..":
                raise ValueError("dotdot member")
            if "\\" in part or any(ord(c) < 32 or ord(c) == 127 for c in part):
                raise ValueError("unsafe component")
            norm.append(part)
        if not norm:
            raise ValueError("empty member")
        canon = "/".join(norm)
        if canon in seen:
            raise ValueError("duplicate member")
        seen.add(canon)
        tops.add(norm[0])
        if member.issym() or member.islnk():
            raise ValueError("link member")
        if member.ischr() or member.isblk() or member.isfifo():
            raise ValueError("device member")
        if not (member.isfile() or member.isdir()):
            raise ValueError("special member")
        if len(norm) < 2:
            continue
        if norm[0] != expected_root:
            continue
        rel = "/".join(norm[1:])
        if rel == "buildpython/__init__.py":
            if not member.isfile():
                raise ValueError("top init must be regular")
            selected.append((member, canon, rel))
        elif rel.startswith("buildpython/openrazer_native/"):
            tail = rel[len("buildpython/openrazer_native/"):]
            if "/" in tail or tail in ("", "__pycache__"):
                continue
            if tail == "README.md" or tail.startswith("README"):
                continue
            if not allowed_native.fullmatch(tail):
                continue
            if not member.isfile():
                raise ValueError("native member must be regular")
            selected.append((member, canon, rel))
        elif rel in ("buildpython/openrazer_packages/pin.py", "buildpython/openrazer_packages/pin.conf", "buildpython/openrazer_packages/dkms-make"):
            if not member.isfile():
                raise ValueError("package member must be regular")
            selected.append((member, canon, rel))
        elif rel == "buildpython/openrazer_packages/__init__.py":
            if not member.isfile():
                raise ValueError("package init must be regular")
            selected.append((member, canon, rel))
    if tops != {expected_root}:
        raise ValueError("single root required")
    need = {"buildpython/__init__.py", "buildpython/openrazer_native/__init__.py", "buildpython/openrazer_native/__main__.py", "buildpython/openrazer_packages/pin.py", "buildpython/openrazer_packages/pin.conf", "buildpython/openrazer_packages/dkms-make"}
    have = {rel for _, _, rel in selected}
    if not need.issubset(have):
        raise ValueError("missing required code file")
    import pathlib
    root = pathlib.Path(dest)
    by_canon = {canon: (m, rel) for m, canon, rel in selected}
    # Re-open to extract by normalized name without following links.
    with tarfile.open(archive, "r:gz") as tar2:
        for m in tar2.getmembers():
            parts = [p for p in m.name.split("/") if p not in ("", ".")]
            canon = "/".join(parts)
            if canon not in by_canon:
                continue
            _, rel = by_canon[canon]
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar2.extractfile(m) as src, open(target, "wb") as out:
                if src is None:
                    raise ValueError("extract none")
                out.write(src.read())
PY
fi

"/usr/bin/python3" -I -B - "$CODE_ROOT/buildpython/openrazer_packages/pin.conf" <<'PY' || die "source pin mismatch; no packages built"
import re
import sys
import pathlib
path = pathlib.Path(sys.argv[1])
fields = {
    "OPENRAZER_FORK_REPO": r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+",
    "OPENRAZER_COMMIT": r"[0-9a-f]{40}",
    "OPENRAZER_BRANCH": r"[A-Za-z0-9][A-Za-z0-9._/-]*",
    "OPENRAZER_PKGVER": r"[0-9][A-Za-z0-9._+]*",
    "OPENRAZER_PKGREL": r"[1-9][0-9]*",
}
pin = {}
for line in path.read_text(encoding="ascii").splitlines():
    if not line.strip() or line.lstrip().startswith("#"):
        continue
    m = re.fullmatch(r'([A-Z_]+)="([^"\n]+)"', line)
    if m is None:
        raise SystemExit(1)
    k, v = m.groups()
    if k not in fields or k in pin:
        raise SystemExit(1)
    if re.fullmatch(fields[k], v) is None or ".." in v:
        raise SystemExit(1)
    pin[k] = v
if set(pin) != set(fields):
    raise SystemExit(1)
if pin["OPENRAZER_FORK_REPO"] != "Rainexn0b/openrazer":
    raise SystemExit(1)
if pin["OPENRAZER_COMMIT"] != "26b0eeb5ed70d638fa3528851adcd5e58369a7f5":
    raise SystemExit(1)
if pin["OPENRAZER_BRANCH"] not in ("naga-v3-pro-compat", "test-pr-2904-edualb"):
    raise SystemExit(1)
if pin["OPENRAZER_PKGVER"] != "3.12.1.pr2904.fix2" or pin["OPENRAZER_PKGREL"] != "1":
    raise SystemExit(1)
PY

SRC_DIR="$tmp/openrazer-src"
mkdir -p "$SRC_DIR"
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES
unset GIT_CONFIG GIT_CONFIG_GLOBAL GIT_CONFIG_SYSTEM GIT_TEMPLATE_DIR GIT_CONFIG_PARAMETERS GIT_CONFIG_COUNT
export GIT_CONFIG_NOSYSTEM=1
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_COUNT=0
GIT_TEMPLATE="$tmp/git-template"
mkdir -p "$GIT_TEMPLATE"
chmod 700 "$GIT_TEMPLATE"
git -c core.hooksPath=/dev/null -c core.fsmonitor=false -c core.templateDir="$GIT_TEMPLATE" init "$SRC_DIR" || die "could not init private OpenRazer checkout"
git -C "$SRC_DIR" -c core.hooksPath=/dev/null -c core.fsmonitor=false remote add origin https://github.com/$OPENRAZER_REPO.git || die "could not configure OpenRazer remote"
git -C "$SRC_DIR" -c core.hooksPath=/dev/null -c core.fsmonitor=false fetch --depth 1 origin "$OPENRAZER_COMMIT" || die "could not fetch pinned OpenRazer $OPENRAZER_COMMIT"
git -C "$SRC_DIR" -c core.hooksPath=/dev/null -c core.fsmonitor=false checkout --detach "$OPENRAZER_COMMIT" || die "could not checkout pinned OpenRazer"
head="$(git -C "$SRC_DIR" -c core.hooksPath=/dev/null -c core.fsmonitor=false rev-parse HEAD)" || die "could not verify OpenRazer HEAD"
[ "$head" = "$OPENRAZER_COMMIT" ] || die "OpenRazer HEAD mismatch; no packages built"
[ -z "$(git -C "$SRC_DIR" -c core.hooksPath=/dev/null -c core.fsmonitor=false status --porcelain --untracked-files=all --ignored)" ] || die "OpenRazer checkout not clean; no packages built"

OUT_DIR="$tmp/output"
[ ! -e "$OUT_DIR" ] || [ ! -L "$OUT_DIR" ] || die "unsafe output directory"
mkdir -p "$OUT_DIR"
[ ! -L "$OUT_DIR" ] || die "unsafe output directory"
[ -O "$OUT_DIR" ] || die "output directory must belong to the desktop user"
chmod 700 "$OUT_DIR"
out_mode="$(stat -Lc '%a' "$OUT_DIR")" || die "could not inspect output directory"
if ! { [[ "$out_mode" =~ ^[0-7]{3,4}$ ]] && (( (8#$out_mode & 0022) == 0 )); }; then
  die "output directory must not be group/other writable"
fi
[ -z "$(ls -A "$OUT_DIR")" ] || die "output directory must start empty"
/usr/bin/python3 -I -B -c 'import runpy,sys; sys.path.insert(0, sys.argv[1]); del sys.argv[1]; runpy.run_module("buildpython.openrazer_native", run_name="__main__")' "$CODE_ROOT" --family "$FAMILY" --source "$SRC_DIR" --output "$OUT_DIR" --pin "$CODE_ROOT/buildpython/openrazer_packages/pin.conf" \
  || die "native local build failed; possible partial prereq changes; no packages installed"

my_id="$(id -u)" || die "could not read installer uid"
for out_file in "$OUT_DIR"/*; do
  [ -f "$out_file" ] || die "invalid native build outputs; no packages installed"
  [ ! -L "$out_file" ] || die "invalid native build outputs; no packages installed"
  owner="$(stat -c '%u' "$out_file")" || die "invalid native build outputs; no packages installed"
  [ "$owner" = "$my_id" ] || die "invalid native build outputs; no packages installed"
  fmode="$(stat -Lc '%a' "$out_file")" || die "invalid native build outputs; no packages installed"
  if ! { [[ "$fmode" =~ ^[0-7]{3,4}$ ]] && (( (8#$fmode & 0022) == 0 )); }; then
    die "invalid native build outputs; no packages installed"
  fi
done

"/usr/bin/python3" -I -B - "$OUT_DIR" "$FAMILY" <<'PY' || die "invalid native build outputs; no packages installed"
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys


def fail(message):
    print("error: invalid native build outputs: " + message, file=sys.stderr)
    sys.exit(1)


try:
    out = pathlib.Path(sys.argv[1])
    family = sys.argv[2]
    roles = ("openrazer-driver-dkms-local", "openrazer-daemon-local", "python-openrazer-local")
    version = "3.12.1.pr2904.fix2-1"
    commit = "26b0eeb5ed70d638fa3528851adcd5e58369a7f5"
    if not out.is_dir() or out.is_symlink():
        fail("output directory")
    entries = sorted(p.name for p in out.iterdir())
    if family == "debian":
        expected_files = sorted(f"{r}_{version}_all.deb" for r in roles)
    else:
        expected_files = sorted(f"{r}-{version}.noarch.rpm" for r in roles)
    expected = sorted(expected_files + ["openrazer-native-packages.sha256", "native-build.json"])
    if entries != expected:
        fail("unexpected output set")
    euid = os.geteuid()
    for name in expected:
        p = out / name
        if p.is_symlink() or not p.is_file():
            fail("not a regular file: " + name)
        st = p.stat()
        if st.st_nlink != 1:
            fail("hardlink not allowed: " + name)
        if st.st_uid != euid:
            fail("foreign owner: " + name)
        if st.st_mode & 0o022:
            fail("group/other writable: " + name)
    raw = (out / "openrazer-native-packages.sha256").read_bytes()
    try:
        text = raw.decode("ascii")
    except UnicodeError:
        fail("manifest encoding")
    if not text.endswith("\n") or text.endswith("\n\n"):
        fail("manifest terminal newline")
    if "\r" in text or "\0" in text:
        fail("manifest controls")
    lines = text.split("\n")[:-1]
    if len(lines) != 3:
        fail("manifest row count")
    if len(set(lines)) != 3:
        fail("duplicate manifest row")
    manifest_map = {}
    for line in lines:
        m = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._+-]*)", line)
        if m is None:
            fail("malformed manifest row")
        digest, fname = m.groups()
        if fname not in expected_files:
            fail("unknown manifest filename")
        if fname in manifest_map:
            fail("duplicate manifest filename")
        actual = hashlib.sha256((out / fname).read_bytes()).hexdigest()
        if actual != digest:
            fail("digest mismatch: " + fname)
        manifest_map[fname] = digest
    role_for = {}
    for r in roles:
        fname = f"{r}_{version}_all.deb" if family == "debian" else f"{r}-{version}.noarch.rpm"
        role_for[r] = fname
    if set(manifest_map) != set(role_for.values()):
        fail("manifest role coverage")
    for r, fname in role_for.items():
        if fname not in manifest_map:
            fail("missing manifest role")
    raw_json = (out / "native-build.json").read_bytes()
    try:
        jtext = raw_json.decode("ascii")
    except UnicodeError:
        fail("json encoding")
    if "\0" in jtext:
        fail("json controls")

    def no_dup(pairs):
        seen = set()
        for k, _ in pairs:
            if k in seen:
                raise ValueError("duplicate json key: " + k)
            seen.add(k)
        return dict(pairs)

    try:
        doc = json.loads(jtext, object_pairs_hook=no_dup)
    except ValueError as error:
        fail("malformed json: " + str(error))
    if not isinstance(doc, dict):
        fail("json top object")
    if set(doc.keys()) != {"schema", "source_commit", "family", "version", "python_minor", "packages"}:
        fail("json top fields")
    schema = doc["schema"]
    if type(schema) is not int or schema != 1:
        fail("json schema")
    if doc["source_commit"] != commit:
        fail("json commit")
    if doc["family"] != family:
        fail("json family")
    if doc["version"] != version:
        fail("json version")
    minor = doc["python_minor"]
    if not isinstance(minor, str) or re.fullmatch(r"3\.([0-9]+)", minor) is None:
        fail("json python_minor type")
    try:
        minor_n = int(minor.split(".")[1])
    except ValueError:
        fail("json python_minor value")
    if minor_n < 10:
        fail("json python_minor range")
    try:
        host = subprocess.check_output(
            ["/usr/bin/python3", "-I", "-B", "-c", "import sys; print(f\"{sys.version_info.major}.{sys.version_info.minor}\")"],
            text=True,
        ).strip()
    except subprocess.SubprocessError as error:
        fail("host python probe: " + str(error))
    if not re.fullmatch(r"3\.[0-9]+", host):
        fail("host python probe format")
    if host != minor:
        fail("host Python outside package bounds: " + host)
    pkgs = doc["packages"]
    if not isinstance(pkgs, list) or len(pkgs) != 3:
        fail("json packages")
    by_role = {}
    for item in pkgs:
        if not isinstance(item, dict):
            fail("json package item")
        if set(item.keys()) != {"role", "filename", "sha256"}:
            fail("json package fields")
        role = item["role"]
        fname = item["filename"]
        digest = item["sha256"]
        if role not in roles or role in by_role:
            fail("json package role")
        if fname != role_for[role]:
            fail("role filename swap")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            fail("json package digest")
        if manifest_map.get(fname) != digest:
            fail("json digest link")
        by_role[role] = item
    if set(by_role) != set(roles):
        fail("json role coverage")
except SystemExit:
    raise
except (ValueError, OSError, UnicodeError, subprocess.SubprocessError) as error:
    print("error: invalid native build outputs: " + str(error), file=sys.stderr)
    sys.exit(1)
PY

if inventory; then
  :
else
  die "native inventory changed before package install; another operator modified OpenRazer; aborting without replacement"
fi
[ "$INVENTORY_ABSENT" -eq 1 ] || die "native inventory changed before package install; aborting"

pkgs=()
if [ "$FAMILY" = "debian" ]; then
  for role in "${ROLES[@]}"; do pkgs+=("$OUT_DIR/${role}_${PACKAGE_VERSION}_all.deb"); done
  sudo apt-get install "${pkgs[@]}" 9>&- || die "native package install failed; possible partial package changes; activation pending, no rollback"
elif [ "$FAMILY" = "fedora" ]; then
  for role in "${ROLES[@]}"; do pkgs+=("$OUT_DIR/${role}-${PACKAGE_VERSION}.noarch.rpm"); done
  sudo dnf install "${pkgs[@]}" 9>&- || die "native package install failed; possible partial package changes; activation pending, no rollback"
else
  for role in "${ROLES[@]}"; do pkgs+=("$OUT_DIR/${role}-${PACKAGE_VERSION}.noarch.rpm"); done
  sudo zypper install --allow-unsigned-rpm "${pkgs[@]}" 9>&- || die "native package install failed; possible partial package changes; activation pending, no rollback"
fi

INSTALL_USER="$(id -un)"
case " $(id -nG) " in
  *" openrazer "*) log "user $INSTALL_USER is already in the openrazer group" ;;
  *)
    if [ "$ADD_GROUP" -ne 1 ] && [ -t 0 ]; then
      answer=""
      read -r -p "Separately add $INSTALL_USER to openrazer (sudo usermod -aG)? [y/N] " answer || true
      case "$answer" in [yY]|[yY][eE][sS]) ADD_GROUP=1 ;; esac
    fi
    if [ "$ADD_GROUP" -eq 1 ]; then
      sudo usermod -aG openrazer "$INSTALL_USER" 9>&- || die "group addition failed; packages installed, activation pending"
    else
      log "group unchanged; if required, explicitly run: sudo usermod -aG openrazer $INSTALL_USER"
      log "permissions pending without openrazer group; input access may fail until re-login"
    fi ;;
esac
systemctl --user daemon-reload 9>&- || die "user unit reload failed; packages installed, activation pending"
systemctl --user enable openrazer-daemon.service 9>&- || die "user daemon enable failed; packages installed, activation pending"
log "Native packages installed; activation DEFERRED. No daemon restart or module reload was attempted."
log "SecureBoot may require operator module signing; DKMS or kernel failures need manual recovery, no changes made here."
log "Reboot/re-login before starting Naga; verify installed inventory, host imports, runtime capabilities and recovery."
log "Panel uninstall retains OpenRazer. Review upgrades as a matching cohort; do not freeze security updates."
