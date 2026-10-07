#!/usr/bin/env bash

# Naga Control installer dispatcher (keyRGB pattern).
#
# Works both:
# - from a repo checkout (runs ./scripts/install_user.sh directly)
# - via curl downloads (bootstraps scripts/ from GitHub raw from main by default)

set -euo pipefail
umask 077

REPO_OWNER="${NAGA_CONTROL_REPO_OWNER:-Rainexn0b}"
REPO_NAME="${NAGA_CONTROL_REPO_NAME:-naga-control}"
BOOTSTRAP_REF="${NAGA_CONTROL_BOOTSTRAP_REF:-main}"

usage() {
  cat <<EOF
Usage:
  install.sh [--ref <git-ref>] [...install_user.sh args]

Bootstrap (curl installs): downloads scripts/ from GitHub raw at the pinned
ref (default: ${BOOTSTRAP_REF}); override with --ref or
NAGA_CONTROL_BOOTSTRAP_REF. From a checkout, always runs the local scripts.
App-only by default. Forward --install-openrazer to explicitly opt in to the
selected release's prerequisites; NAGA_CONTROL_INSTALL_OPENRAZER=0 hard skips.

Examples:
  (umask 077; d=\$(mktemp -d) && trap 'rm -rf "\$d"' EXIT && trap 'exit 130' INT && trap 'exit 143' HUP TERM && curl -fsSL https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/v0.4.0/install.sh -o "\$d/install.sh" && bash "\$d/install.sh" --ref v0.4.0 --version v0.4.0)
  # Add --install-openrazer to that bash command for explicit opt-in.
  # New checkout installer safety is not retroactive to published older scripts.
  ./install.sh --version v0.4.0
EOF
}

REF_OVERRIDE=""
args=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --ref) [ "$#" -ge 2 ] && [ -n "$2" ] || { echo "error: --ref requires a ref" >&2; exit 1; }; REF_OVERRIDE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) args+=("$1"); shift ;;
  esac
done
[ -n "$REF_OVERRIDE" ] && BOOTSTRAP_REF="$REF_OVERRIDE"

die() { echo "error: $*" >&2; exit 1; }

case "${NAGA_CONTROL_INSTALL_OPENRAZER-}" in
  0|1) ;;
  "") [ "${NAGA_CONTROL_INSTALL_OPENRAZER+x}" != x ] || die "NAGA_CONTROL_INSTALL_OPENRAZER must be 0, 1, or unset" ;;
  *) die "NAGA_CONTROL_INSTALL_OPENRAZER must be 0, 1, or unset" ;;
esac

run_local() {
  local script="$1"; shift
  exec bash "$script" "$@"
}

bootstrap_and_run() {
  local script="$1"; shift
  command -v curl >/dev/null || die "curl is required for curl installs"
  printf '%s' "$REPO_OWNER" | grep -Eq '^[a-zA-Z0-9-]{1,39}$' \
    || die "invalid NAGA_CONTROL_REPO_OWNER '$REPO_OWNER'"
  printf '%s' "$REPO_NAME" | grep -Eq '^[a-zA-Z0-9._-]{1,100}$' \
    || die "invalid NAGA_CONTROL_REPO_NAME '$REPO_NAME'"
  case "$BOOTSTRAP_REF" in
    main|master|HEAD|develop)
      echo "warning: bootstrap ref '$BOOTSTRAP_REF' is a mutable branch; prefer a tagged release for reproducible installs" >&2
      ;;
  esac
  BOOTSTRAP_TMP="$(mktemp -d "${TMPDIR:-/tmp}/naga-bootstrap.XXXXXX")"
  trap 'rm -rf "$BOOTSTRAP_TMP"' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  trap 'exit 129' HUP
  mkdir -p "$BOOTSTRAP_TMP/scripts"
  local base="https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/${BOOTSTRAP_REF}"
  curl -fsSL "$base/scripts/install_user.sh" -o "$BOOTSTRAP_TMP/scripts/install_user.sh" \
    || die "could not bootstrap install_user.sh from $BOOTSTRAP_REF"
  curl -fsSL "$base/scripts/uninstall.sh" -o "$BOOTSTRAP_TMP/scripts/uninstall.sh" \
    || die "could not bootstrap uninstall.sh from $BOOTSTRAP_REF"
  # The optional prerequisite helper is fetched by install_user.sh only on
  # explicit opt-in, from the selected release tag (not this bootstrap ref).
  # Preserve terminal stdin even for the owned child used to relay interruption.
  # Signal only this installer child, never GUI/daemon processes or arbitrary PIDs.
  exec 8<&0
  bash "$BOOTSTRAP_TMP/$script" "$@" 0<&8 8<&- &
  BOOTSTRAP_CHILD=$!
  trap 'kill -TERM "$BOOTSTRAP_CHILD" 2>/dev/null || true; wait "$BOOTSTRAP_CHILD" || true; exit 130' INT
  trap 'kill -TERM "$BOOTSTRAP_CHILD" 2>/dev/null || true; wait "$BOOTSTRAP_CHILD" || true; exit 143' TERM
  trap 'kill -TERM "$BOOTSTRAP_CHILD" 2>/dev/null || true; wait "$BOOTSTRAP_CHILD" || true; exit 129' HUP
  wait "$BOOTSTRAP_CHILD"
}

SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/scripts/install_user.sh" ]; then
  run_local "$SCRIPT_DIR/scripts/install_user.sh" ${args+"${args[@]}"}
else
  bootstrap_and_run "scripts/install_user.sh" ${args+"${args[@]}"}
fi
