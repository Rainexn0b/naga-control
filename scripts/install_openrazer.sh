#!/usr/bin/env bash

# Optional experimental Arch/pacman prerequisite installer. No hardware access.
set -euo pipefail
umask 077
HOME="${HOME%/}"

REPO="Rainexn0b/naga-control"
VERSION="${NAGA_CONTROL_VERSION:-}"
SOURCE_COMMIT="26b0eeb5ed70d638fa3528851adcd5e58369a7f5"
PACKAGE_VERSION="3.12.1.pr2904.fix2-1"
PACKAGES=(openrazer-driver-dkms-local openrazer-daemon-local python-openrazer-local)
INSTALL=0
YES=0
CHECK=0
PREFLIGHT=0
ADD_GROUP=0

die() { echo "error: $*" >&2; exit 1; }
log() { echo "==> $*"; }
usage() {
  cat <<'EOF'
usage: install_openrazer.sh [--check | --preflight] [--version <tag>] [--install | --yes]
                           [--add-openrazer-group]
Default/--check: read-only installed inventory, no network or hardware calls.
--preflight: read-only install-environment prerequisites, no network, prompts,
lock/state writes, package changes or unit configuration; overrides install flags.
--install: explicitly reinstall the entire selected cohort; confirm the summary.
--yes: opt in and skip ONLY the summary confirmation, NOT pacman's prompts.
--add-openrazer-group: separate consent to add the actual id -un user.
NAGA_CONTROL_INSTALL_OPENRAZER=1 opts in (summary still required); =0 is a
hard skip even with flags. Unset is read-only; other values are errors.
Only experimental Arch/pacman with the packages' builder Python minor is
supported. See docs/release-notes.md before replacing a working installation.
EOF
}
while [ "$#" -gt 0 ]; do
  case "$1" in
    --version) [ "$#" -ge 2 ] || die "--version requires a tag"; VERSION="$2"; shift 2 ;;
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

inventory() {
  local known=1 package installed_package record stamp
  if command -v pacman >/dev/null; then
    for package in "${PACKAGES[@]}"; do
      installed_package="$package"
      record="$(pacman -Q "$package" 2>/dev/null || true)"
      if [ -z "$record" ]; then
        installed_package="${package%-local}"
        record="$(pacman -Q "$installed_package" 2>/dev/null || true)"
      fi
      stamp="$(cat "/usr/share/doc/$installed_package/source-commit" 2>/dev/null || true)"
      log "installed ${record:-$package: missing}; source ${stamp:-unstamped}"
      [ "$record" = "$package $PACKAGE_VERSION" ] && [ "$stamp" = "$SOURCE_COMMIT" ] || known=0
    done
  else
    known=0
    log "pacman unavailable: installed package cohort unknown"
  fi
  if [ "$known" -eq 1 ]; then
    log "KNOWN PINNED COHORT: consistent package versions and exact source stamps (not hardware acceptance)"
  else
    log "UNVERIFIED: older, partial, mixed, upstream, or unstamped builds; support is unknown, not proven absent"
  fi
  if [ -x "/usr/bin/python3" ]; then
    "/usr/bin/python3" -I -B -c 'from importlib.machinery import PathFinder; p = PathFinder.find_spec("openrazer"); c = PathFinder.find_spec("openrazer.client", p.submodule_search_locations) if p else None; d = PathFinder.find_spec("openrazer_daemon"); print("Host import discoverability: openrazer.client=" + str(c is not None) + ", openrazer_daemon=" + str(d is not None))' \
      || die "host Python inventory failed"
  else
    log "Host import discoverability: unknown (/usr/bin/python3 unavailable)"
  fi
  log "Runtime capabilities, module activation, permissions, and idle/wake recovery still pending; no device or daemon calls made"
}
preflight() {
  local executable kernel build
  command -v id >/dev/null || die "id is required"
  [ "$(id -u)" -ne 0 ] || die "run as your desktop user, not root"
  [ -z "$VERSION" ] || [[ "$VERSION" =~ ^[a-zA-Z0-9][a-zA-Z0-9._+-]*$ ]] || die "invalid release tag"
  [ -x "/usr/bin/python3" ] || die "/usr/bin/python3 is required (system interpreter, not a virtualenv alias)"
  for executable in curl pacman bsdtar sha256sum sudo systemctl busctl uname grep mktemp rm flock stat mkdir dirname; do
    command -v "$executable" >/dev/null || die "$executable is required (experimental Arch/pacman path only)"
  done
  [ "$(uname -s)" = Linux ] && [ "$(uname -m)" = x86_64 ] || die "this experimental installer requires Linux x86_64"
  # Parser uses str.removeprefix/removesuffix (Python 3.9+). These checks are
  # metadata/tool discovery only: no compilation, device probes or module calls.
  "/usr/bin/python3" -I -B -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
    || die "host Python 3.9+ is required by the validation parser"
  kernel="$(uname -r)"
  build="/usr/lib/modules/$kernel/build"
  [ -d "$build" ] && [ -r "$build/Makefile" ] && [ -r "$build/.config" ] \
    || die "active-kernel headers/build tree and .config missing for $kernel; install matching Arch linux-headers (or your kernel's headers package)"
  for executable in cc make dkms; do
    command -v "$executable" >/dev/null || die "$executable is required; install Arch base-devel and dkms before opting in"
  done
  if grep -Eq '^CONFIG_CC_IS_CLANG=y$' "$build/.config"; then
    for executable in clang ld.lld llvm-ar llvm-nm llvm-objcopy llvm-objdump llvm-readelf llvm-strip; do
      command -v "$executable" >/dev/null || die "$executable is required for this Clang kernel; install Arch clang llvm lld before opting in"
    done
  fi
  systemctl --user show --property=Version --value 9>&- >/dev/null \
    || die "user systemd unavailable; log into a normal desktop session before opting in"
  busctl --user status 9>&- >/dev/null \
    || die "session D-Bus unavailable; log into a desktop session with dbus-user-session/dbus before opting in"
  log "Build preflight covers only active kernel $kernel; install headers/toolchains for every other intended kernel. DKMS hooks can still fail."
}
if [ "$PREFLIGHT" -eq 1 ]; then
  preflight
  log "Read-only install preflight passed; no network, lock/state writes, prompts, package changes or unit configuration. Release hashes/builder Python bounds and runtime readiness remain unverified."
  exit 0
fi
inventory
[ "$INSTALL" -eq 1 ] && [ "$CHECK" -ne 1 ] || exit 0
preflight
# Serialize standalone opt-in with app installs too. A foreground app helper
# can inherit the already-locked same inode; no environment variable bypass.
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
log "Explicit reinstall: all three pinned packages, even at the same version, in one interactive pacman transaction."
log "Before continuing, stop Naga/other OpenRazer clients and save previous package archives/version list."
log "No live daemon/module restart. Reboot/re-login and runtime verification are required."
if [ "$YES" -ne 1 ]; then
  [ -t 0 ] || die "summary confirmation requires a terminal; --yes skips only this confirmation, never pacman prompts"
  answer=""
  read -r -p "Install/reinstall the complete pinned cohort (sudo pacman -U; pacman's prompts remain)? [y/N] " answer || true
  case "$answer" in
    [yY]|[yY][eE][sS]) ;;
    *) die "OpenRazer install declined; nothing installed" ;;
  esac
fi
if [ -z "$VERSION" ]; then
  resolved="$(curl -fsSL -o /dev/null -w '%{url_effective}' "https://github.com/$REPO/releases/latest")" \
    || die "could not resolve latest release; pass --version <tag>"
  VERSION="${resolved##*/}"
fi
[[ "$VERSION" =~ ^[a-zA-Z0-9][a-zA-Z0-9._+-]*$ ]] || die "invalid release tag"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
base="https://github.com/$REPO/releases/download/$VERSION"
curl -fsSL -o "$tmp/pin.conf" "https://raw.githubusercontent.com/$REPO/$VERSION/buildpython/openrazer_packages/pin.conf" \
  || die "could not fetch source pin for $VERSION"
curl -fsSL -o "$tmp/openrazer-arch-packages.sha256" "$base/openrazer-arch-packages.sha256" \
  || die "could not fetch complete package manifest for $VERSION"

# Parse fetched data, never source/execute pin.conf. All filenames are validated
# before downloads; archive metadata is read offline without extracting files.
validate() {
  "/usr/bin/python3" -I -B - "$1" "$tmp" <<'PY'
import collections
import pathlib
import re
import subprocess
import sys

mode, directory = sys.argv[1:]
root = pathlib.Path(directory)
roles = ("openrazer-driver-dkms-local", "openrazer-daemon-local", "python-openrazer-local")
expected = {
    "OPENRAZER_FORK_REPO": "Rainexn0b/openrazer",
    "OPENRAZER_COMMIT": "26b0eeb5ed70d638fa3528851adcd5e58369a7f5",
    "OPENRAZER_PKGVER": "3.12.1.pr2904.fix2",
    "OPENRAZER_PKGREL": "1",
}
pin_fields = {
    "OPENRAZER_FORK_REPO": r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+",
    "OPENRAZER_COMMIT": r"[0-9a-f]{40}",
    "OPENRAZER_BRANCH": r"[A-Za-z0-9][A-Za-z0-9._/-]*",
    "OPENRAZER_PKGVER": r"[0-9][A-Za-z0-9._+]*",
    "OPENRAZER_PKGREL": r"[1-9][0-9]*",
}

def require(condition, message):
    if not condition:
        raise ValueError(message)

def fields(text):
    result = collections.defaultdict(list)
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition(" = ")
        require(separator and key and value, "invalid .PKGINFO row")
        result[key].append(value)
    return result

def archive_members(archive):
    listing = subprocess.check_output(["bsdtar", "-tf", str(archive)]).decode("utf-8")
    members = {}
    for raw in listing.removesuffix("\n").split("\n"):
        if raw == "./":
            continue
        name = raw.removeprefix("./").removesuffix("/")
        require(name and not name.startswith("/")
                and all(part not in ("", ".", "..") for part in name.split("/"))
                and "\\" not in name
                and not any(ord(char) < 32 or ord(char) == 127 for char in name)
                and name not in members, "unsafe or duplicate archive member")
        members[name] = raw
    require(all(member in members and not members[member].endswith("/")
                for member in (".PKGINFO", ".BUILDINFO")), "missing package metadata/provenance")
    return members

def archive_text(archive, member, members):
    require(member in members and not members[member].endswith("/"), "missing archive member: " + member)
    return subprocess.check_output(["bsdtar", "-xOf", str(archive), "--", members[member]]).decode("utf-8")

try:
    pin = {}
    for line in (root / "pin.conf").read_text(encoding="ascii").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r'([A-Z_]+)="([^"\n]+)"', line)
        require(match is not None, "invalid source pin data")
        key, value = match.groups()
        require(key in pin_fields and key not in pin, "unknown/duplicate pin field")
        require(re.fullmatch(pin_fields[key], value) is not None and ".." not in value, "unsafe pin field")
        pin[key] = value
    require(pin.keys() == pin_fields.keys(), "missing required pin fields")
    # A future pin change requires deliberate review of this authorized guard.
    require(all(pin.get(key) == value for key, value in expected.items()), "source pin mismatch")
    version = pin["OPENRAZER_PKGVER"] + "-" + pin["OPENRAZER_PKGREL"]
    lines = (root / "openrazer-arch-packages.sha256").read_text(encoding="ascii").splitlines()
    require(len(lines) == 3, "manifest must contain exactly three canonical rows")
    names = {}
    for line in lines:
        match = re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._+-]*)', line)
        require(match is not None, "malformed digest or unsafe manifest filename")
        digest, name = match.groups()
        candidates = [role for role in roles if name == role + "-" + version + "-any.pkg.tar.zst"]
        require(len(candidates) == 1, "unknown role or mismatched manifest version")
        role = candidates[0]
        require(role not in names, "duplicate manifest role")
        names[role] = name
    require(set(names) == set(roles), "missing manifest role")
    if mode == "manifest":
        (root / "names").write_text("".join(names[role] + "\n" for role in roles), encoding="ascii")
    elif mode == "archives":
        python_bounds = []
        for role in roles:
            archive = root / names[role]
            members = archive_members(archive)
            metadata = fields(archive_text(archive, ".PKGINFO", members))
            require(metadata["pkgname"] == [role], "archive package name mismatch")
            require(metadata["pkgver"] == [version], "archive package version mismatch")
            require(metadata["arch"] == ["any"], "archive architecture mismatch")
            stamp = archive_text(archive, "usr/share/doc/" + role + "/source-commit", members)
            require(stamp == pin["OPENRAZER_COMMIT"] + "\n", "archive source stamp mismatch")
            dependencies = metadata["depend"]
            linked = [item for item in dependencies if item.startswith(("openrazer-", "python-openrazer"))]
            required_links = {
                roles[0]: [], roles[1]: [roles[0] + "=" + version], roles[2]: [roles[1] + "=" + version],
            }
            require(linked == required_links[role], "archive linked dependencies mismatch")
            if role != roles[0]:
                bounds = [item for item in dependencies if re.match(r"^python(?:[<>=]|$)", item)]
                lower = [re.fullmatch(r"python>=3\.(\d+)", item) for item in bounds]
                upper = [re.fullmatch(r"python<3\.(\d+)", item) for item in bounds]
                low = [int(item[1]) for item in lower if item]
                high = [int(item[1]) for item in upper if item]
                require(len(bounds) == 2 and len(low) == len(high) == 1 and high[0] == low[0] + 1,
                        "missing/invalid builder Python minor bounds")
                python_bounds.append((3, low[0]))
                prefix = f"usr/lib/python3.{low[0]}/site-packages/"
                package = "openrazer_daemon" if role == roles[1] else "openrazer"
                init = prefix + package + "/__init__.py"
                require(init in members and not members[init].endswith("/"),
                        "missing Python package at declared builder minor")
                require(not any(member.startswith("usr/lib/python")
                                and ("/site-packages/" in member or member.endswith("/site-packages"))
                                and member != prefix.removesuffix("/") and not member.startswith(prefix)
                                for member in members), "Python installation path disagrees with dependency bounds")
        require(len(set(python_bounds)) == 1, "mixed builder Python minor bounds")
        host = subprocess.check_output(["/usr/bin/python3", "-I", "-B", "-c",
                                       "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"], text=True).strip()
        require(re.fullmatch(r"3\.\d+", host) is not None, "invalid host Python version")
        require(tuple(map(int, host.split("."))) == python_bounds[0], "host Python outside package bounds: " + host)
    else:
        raise ValueError("invalid validation mode")
except (ValueError, OSError, UnicodeError, subprocess.SubprocessError) as error:
    print("error: package validation failed: " + str(error), file=sys.stderr)
    sys.exit(1)
PY
}
validate manifest || die "invalid release manifest/source pin; no packages installed"
mapfile -t names < "$tmp/names"
for name in "${names[@]}"; do
  curl -fsSL -o "$tmp/$name" "$base/$name" || die "package download failed: $name"
done
(cd "$tmp" && sha256sum -c openrazer-arch-packages.sha256) || die "package checksum verification failed"
validate archives || die "invalid package metadata or host Python; no packages installed"

archives=()
for name in "${names[@]}"; do archives+=("$tmp/$name"); done
sudo pacman -U "${archives[@]}" 9>&- || die "pacman transaction failed; inspect installed cohort before activation"

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
    fi ;;
esac
systemctl --user daemon-reload 9>&- || die "user unit reload failed; packages installed, activation pending"
systemctl --user enable openrazer-daemon.service 9>&- || die "user daemon enable failed; packages installed, activation pending"
log "Packages installed; activation DEFERRED. No daemon restart or module reload was attempted."
log "Reboot/re-login before starting Naga; verify installed stamps, host imports, runtime capabilities and recovery."
log "Panel uninstall retains OpenRazer. Review upgrades as a matching cohort; do not freeze security updates."
