#!/usr/bin/env bash
# Checkout-only, offline advice. No installer API or eligibility decision.
# Private functions are a fake-test seam, not configurable production inputs.

_dr_etc_path() { printf '%s' /etc/os-release; }
_dr_vendor_path() { printf '%s' /usr/lib/os-release; }
_dr_readable() { [[ -r "$1" ]]; }
_dr_uname() { command uname "$1" 2>/dev/null; }

_dr_bad_data() {
  _dr_id=UNKNOWN
  _dr_like=''
  _dr_version=UNKNOWN
  _dr_version_present=0
  _dr_data=UNKNOWN
  _dr_reason="$1"
}

_dr_value() {
  local raw="$1" key="$2" quote
  case "$raw" in
    \"*|\'*)
      quote="${raw:0:1}"
      [[ ${#raw} -ge 2 && "${raw: -1}" == "$quote" ]] || return 1
      raw="${raw:1:${#raw}-2}"
      ;;
  esac
  case "$key" in
    ID) [[ "$raw" =~ ^[a-z0-9._-]+$ ]] || return 1 ;;
    ID_LIKE) [[ "$raw" =~ ^[a-z0-9._-]+(\ +[a-z0-9._-]+)*$ ]] || return 1 ;;
    VERSION_ID) [[ "$raw" =~ ^[A-Za-z0-9._+-]+$ ]] || return 1 ;;
  esac
  _dr_value_result="$raw"
}

_dr_line() {
  local line="$1" key raw
  # CR is removed only for CRLF by the caller. Other controls are invalid,
  # even in ignored fields; no raw line or untrusted diagnostic is printed.
  [[ ! "$line" =~ [[:cntrl:]] ]] || return 1
  case "$line" in ''|\#*) return 0 ;; esac
  # Unrelated keys/assignments/substitutions are ignored as DATA, never run.
  if [[ ! "$line" =~ ^\ *(ID|ID_LIKE|VERSION_ID)([^A-Za-z0-9_]|$) ]]; then
    return 0
  fi
  [[ "$line" =~ ^(ID|ID_LIKE|VERSION_ID)= ]] || return 1
  key="${BASH_REMATCH[1]}"
  raw="${line#*=}"
  case "$key" in
    ID) [[ $_dr_seen_id == 0 ]] || return 1; _dr_seen_id=1 ;;
    ID_LIKE) [[ $_dr_seen_like == 0 ]] || return 1; _dr_seen_like=1 ;;
    VERSION_ID) [[ $_dr_seen_version == 0 ]] || return 1; _dr_seen_version=1 ;;
  esac
  _dr_value "$raw" "$key" || return 1
  case "$key" in
    ID) _dr_id="$_dr_value_result" ;;
    ID_LIKE) _dr_like="$_dr_value_result" ;;
    VERSION_ID) _dr_version="$_dr_value_result"; _dr_version_present=1 ;;
  esac
}

_dr_load() {
  local path data='' line newline
  local _dr_seen_id=0 _dr_seen_like=0 _dr_seen_version=0 _dr_value_result=''
  _dr_bad_data 'missing identity file'
  _dr_source=UNKNOWN
  path="$(_dr_etc_path)"
  # A present malformed/unreadable/special file or dangling symlink never
  # falls back. Ordinary symlinks resolving to readable regular files work.
  if [[ -e "$path" || -L "$path" ]]; then
    _dr_source=/etc/os-release
  else
    path="$(_dr_vendor_path)"
    if [[ ! -e "$path" && ! -L "$path" ]]; then return 0; fi
    _dr_source=/usr/lib/os-release
  fi
  if [[ ! -f "$path" ]] || ! _dr_readable "$path"; then
    _dr_bad_data 'identity file is not a readable regular file'
    return 0
  fi
  # In C locale, -n bounds bytes. With -d '', read stops at NUL rather than
  # silently stripping it. Success means NUL or the 65537-byte sentinel:
  # both are invalid. EOF with <=65536 bytes is the only accepted result.
  # No command substitution, here-string, or temporary file holds this data.
  if { IFS= read -r -d '' -n 65537 data < "$path"; } 2>/dev/null; then
    _dr_bad_data 'NUL byte or input exceeds 64 KiB'
    return 0
  fi
  _dr_id=UNKNOWN
  _dr_like=''
  _dr_version=UNKNOWN
  while [[ -n "$data" ]]; do
    newline=0
    if [[ "$data" == *$'\n'* ]]; then
      line="${data%%$'\n'*}"
      data="${data#*$'\n'}"
      newline=1
    else
      line="$data"
      data=''
    fi
    if [[ ${#line} -gt 4096 ]]; then
      _dr_bad_data 'line exceeds 4096 bytes'
      return 0
    fi
    if [[ "$newline" == 1 ]]; then line="${line%$'\r'}"; fi
    if ! _dr_line "$line"; then
      _dr_bad_data 'malformed, duplicate, or control-byte identity data'
      return 0
    fi
  done
  if [[ $_dr_seen_id != 1 ]]; then
    _dr_bad_data 'missing ID'
    return 0
  fi
  _dr_data=PARSED
  _dr_reason='identity parsed as data; absent VERSION_ID stays unknown'
}

_dr_family_token() {
  case "$1" in
    ubuntu) printf '%s' ubuntu ;;
    debian) printf '%s' debian ;;
    arch|archlinux) printf '%s' arch ;;
    fedora|rhel|centos|rocky|almalinux) printf '%s' fedora ;;
    opensuse|opensuse-leap|opensuse-tumbleweed|suse|sles) printf '%s' opensuse ;;
    alpine) printf '%s' alpine ;;
    *) printf '%s' UNKNOWN ;;
  esac
}

_dr_family() {
  local rest="$_dr_like" token candidate lineage chosen_lineage=''
  _dr_family=UNKNOWN
  _dr_provenance=UNKNOWN
  [[ $_dr_data == PARSED ]] || return 0
  candidate="$(_dr_family_token "$_dr_id")"
  if [[ "$candidate" != UNKNOWN ]]; then
    _dr_family="$candidate"
    _dr_provenance=ID
    return 0
  fi
  # First recognized parent wins within a related lineage (ubuntu/debian,
  # fedora/rhel, suse aliases). Unrelated recognized lineages are ambiguous.
  while [[ -n "$rest" ]]; do
    token="${rest%% *}"
    if [[ "$rest" == *' '* ]]; then
      rest="${rest#* }"
    else
      rest=''
    fi
    [[ -n "$token" ]] || continue
    candidate="$(_dr_family_token "$token")"
    [[ "$candidate" != UNKNOWN ]] || continue
    lineage="$candidate"
    case "$candidate" in ubuntu|debian) lineage=debian ;; esac
    if [[ -z "$chosen_lineage" ]]; then
      chosen_lineage="$lineage"
      _dr_family="$candidate"
      _dr_provenance='ID_LIKE (hint only)'
    elif [[ "$lineage" != "$chosen_lineage" ]]; then
      _dr_family=UNKNOWN
      _dr_provenance='UNKNOWN (ambiguous ID_LIKE)'
      return 0
    fi
  done
}

_dr_platform() {
  _dr_os="$(_dr_uname -s)" || _dr_os=UNKNOWN
  _dr_arch="$(_dr_uname -m)" || _dr_arch=UNKNOWN
  if [[ ! "$_dr_os" =~ ^[A-Za-z0-9._-]{1,64}$ ]]; then _dr_os=UNKNOWN; fi
  if [[ ! "$_dr_arch" =~ ^[A-Za-z0-9._-]{1,64}$ ]]; then _dr_arch=UNKNOWN; fi
}

_dr_plan() {
  _dr_status=UNKNOWN
  _dr_package=UNKNOWN
  _dr_url=UNKNOWN
  _dr_review='NOT REVIEWED'
  _dr_plan_note='no reviewed exact release row; manual distribution context required'
  if [[ $_dr_os != Linux || $_dr_arch != x86_64 ]]; then
    _dr_plan_note='outside current managed Linux x86_64 target or platform unknown'
    return 0
  fi
  [[ $_dr_data == PARSED ]] || return 0
  if [[ $_dr_id == alpine ]]; then
    _dr_plan_note='musl distribution outside current managed glibc target'
    return 0
  fi
  case "$_dr_id:$_dr_version" in
    ubuntu:22.04)
      _dr_package='libfuse2 (universe)'
      _dr_url=https://packages.ubuntu.com/jammy/libfuse2
      ;;
    ubuntu:24.04)
      _dr_package='libfuse2t64 (universe)'
      _dr_url=https://packages.ubuntu.com/noble/libfuse2t64
      ;;
    arch:UNKNOWN)
      [[ $_dr_version_present == 0 ]] || return 0
      _dr_package='fuse2 (extra)'
      _dr_url=https://archlinux.org/packages/extra/x86_64/fuse2/
      ;;
    *) return 0 ;;
  esac
  _dr_status=CONDITIONAL
  _dr_review=2026-10-08
  _dr_plan_note='manual FUSE2 reference only; verify actual architecture and prerequisites'
}

_dr_print() {
  printf '%s\n' \
    'Naga distro report - read-only, offline advice; not installer consent or eligibility' \
    "Report status: $_dr_status" \
    "OS: $_dr_os" \
    "Architecture: $_dr_arch" \
    "Identity source: $_dr_source" \
    "Identity data: $_dr_data" \
    "Identity note: $_dr_reason" \
    "ID: $_dr_id" \
    "VERSION_ID: $_dr_version" \
    'Version policy: own release string only; never a parent release version' \
    "Family: $_dr_family" \
    "Family provenance: $_dr_provenance" \
    'Approved build target: Ubuntu 22.04 / glibc 2.35 / x86_64 (not artifact acceptance)' \
    'Artifact audit: NOT EXAMINED' \
    'Host libc: NOT EXAMINED' \
    'Qt platform libraries: NOT EXAMINED' \
    'Desktop session / user systemd / session D-Bus: NOT EXAMINED' \
    'FUSE library / runtime / kernel access: NOT EXAMINED' \
    'udev / input permissions: NOT EXAMINED' \
    'Kernel / DKMS / Secure Boot: NOT EXAMINED' \
    'Actual OpenRazer runtime: NOT EXAMINED' \
    'Installed package presence: NOT EXAMINED' \
    "Plan note: $_dr_plan_note" \
    "FUSE2 package reference: $_dr_package" \
    "FUSE2 reference URL: $_dr_url" \
    "FUSE2 reference reviewed: $_dr_review" \
    'FUSE2 plan: manual only; package presence and runtime NOT checked; no auto-install' \
    'AppImage plan: ordinary installation is app-only; host glibc/Qt libraries, desktop session, FUSE and scoped udev/input permissions remain unexamined; managed integration needs normal FUSE, not extraction' \
    'Source development plan: optional Python >=3.12; not a host-report or ordinary AppImage Python prerequisite' \
    'OpenRazer policy: optional experimental Arch-only helper requires explicit opt-in and matching driver/daemon/client; independent helper eligibility is unchanged' \
    'OpenRazer native plan: other distributions/derivatives need a manual matching-source native build with distribution context; no Arch archive conversion or new automated .deb/.rpm provisioning' \
    'OpenRazer prerequisites: matching headers and toolchain for every intended kernel; DKMS/Secure Boot unresolved; actual host daemon/client Python minor requires manual matching' \
    'Rolling policy: Arch immutable current artifact/snapshot UNKNOWN; derivatives never inherit release or artifact validation' \
    'Guidance: docs/troubleshooting.md#installer-prerequisites' \
    'Native build guidance: docs/release-notes.md#other-distributions-manual-matching-source-native-build' \
    'Scope: no current distro/artifact validation; no package queries, device access, network, prompts, or filesystem changes'
}

_dr_main() (
  export LC_ALL=C
  if [[ $# == 1 && "$1" == --help ]]; then
    printf '%s\n' 'usage: bash scripts/distro_report.sh [--help]' \
      'Default: offline, read-only facts and manual prerequisite plans, not install eligibility.' \
      'Identity: /etc/os-release; /usr/lib/os-release only if /etc/os-release is absent.' \
      'Data grammar: ID/ID_LIKE lowercase safe tokens; VERSION_ID safe release string.' \
      'Matching single/double quotes or unquoted values; ID_LIKE permits internal spaces.' \
      'Limits: 64 KiB input, 4096 bytes/line; duplicates, malformed values, NUL and controls are UNKNOWN.' \
      'CRLF and a final line without newline are accepted. No configuration is executed.' \
      'UNKNOWN reports exit 0; invalid arguments exit 2. No host Python required.'
    return 0
  fi
  if [[ $# != 0 ]]; then
    printf '%s\n' 'error: only --help or no arguments are accepted' >&2
    return 2
  fi
  local _dr_id _dr_like _dr_version _dr_version_present _dr_data _dr_reason _dr_source
  local _dr_family _dr_provenance _dr_os _dr_arch
  local _dr_status _dr_package _dr_url _dr_review _dr_plan_note
  _dr_load
  _dr_family
  _dr_platform
  _dr_plan
  _dr_print
)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  _dr_main "$@"
fi
