#!/usr/bin/env bash

# Naga Control installer dispatcher (keyRGB pattern).
#
# Works both:
# - from a repo checkout (runs ./scripts/install_user.sh directly)
# - via curl downloads (bootstraps scripts/ from GitHub raw from main by default)

set -euo pipefail

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

Examples:
  curl -fsSL https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/main/install.sh -o install.sh && bash install.sh
  curl -fsSL https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/v0.1.0/install.sh -o install.sh && bash install.sh --ref v0.1.0 --version v0.1.0
  ./install.sh --version v0.1.0
EOF
}

REF_OVERRIDE=""
args=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --ref) REF_OVERRIDE="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) args+=("$1"); shift ;;
  esac
done
[ -n "$REF_OVERRIDE" ] && BOOTSTRAP_REF="$REF_OVERRIDE"

die() { echo "error: $*" >&2; exit 1; }

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
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  mkdir -p "$tmp/scripts"
  local base="https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/${BOOTSTRAP_REF}"
  curl -fsSL "$base/scripts/install_user.sh" -o "$tmp/scripts/install_user.sh" \
    || die "could not bootstrap install_user.sh from $BOOTSTRAP_REF"
  curl -fsSL "$base/scripts/uninstall.sh" -o "$tmp/scripts/uninstall.sh" \
    || die "could not bootstrap uninstall.sh from $BOOTSTRAP_REF"
  exec bash "$tmp/$script" "$@"
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
