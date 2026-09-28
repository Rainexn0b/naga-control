#!/usr/bin/env bash

# Naga Control uninstall dispatcher (keyRGB pattern).
#
# Works from a checkout (runs ./scripts/uninstall.sh) or via curl downloads
# (bootstraps the uninstall script from GitHub raw from main by default).

set -euo pipefail

REPO_OWNER="${NAGA_CONTROL_REPO_OWNER:-Rainexn0b}"
REPO_NAME="${NAGA_CONTROL_REPO_NAME:-naga-control}"
BOOTSTRAP_REF="${NAGA_CONTROL_BOOTSTRAP_REF:-main}"

usage() {
  cat <<EOF
Usage:
  uninstall.sh [--ref <git-ref>] [-y|--yes] [--purge-config]

Bootstrap (curl installs): downloads scripts/uninstall.sh from GitHub raw at
the pinned ref (default: ${BOOTSTRAP_REF}).

Example:
  curl -fsSL https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/main/uninstall.sh -o uninstall.sh && bash uninstall.sh --yes --purge-config
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

SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/scripts/uninstall.sh" ]; then
  exec bash "$SCRIPT_DIR/scripts/uninstall.sh" ${args+"${args[@]}"}
fi

command -v curl >/dev/null || die "curl is required for curl installs"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl -fsSL \
  "https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/${BOOTSTRAP_REF}/scripts/uninstall.sh" \
  -o "$tmp/uninstall.sh" || die "could not bootstrap uninstall.sh from $BOOTSTRAP_REF"
exec bash "$tmp/uninstall.sh" ${args+"${args[@]}"}
