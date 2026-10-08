#!/bin/bash
# Controlled Ubuntu 22.04 toolchain driver for the existing AppImage step.
# Build, static finished-artifact gate, then baseline userspace check.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: portable-build.sh [--help]
Build the existing AppImage step inside a controlled Ubuntu 22.04 image,
then run the static finished-artifact ABI gate before any bundled
execution, then run the Ubuntu 22.04 baseline userspace smoke check.
The static gate uses the same built image id with --baseline-root / in a
separate read-only, offline, non-root container. A passing run reports the
static gate plus baseline smoke only; desktop and hardware acceptance still
require separate evidence.
USAGE
}

if [ "$#" -gt 1 ]; then
  echo "portable-build.sh: expected at most one argument" >&2
  exit 2
fi
if [ "$#" -eq 1 ]; then
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "portable-build.sh: unknown argument: $1" >&2
      exit 2
      ;;
  esac
fi

os_name="$(uname -s)"
if [ "$os_name" != "Linux" ]; then
  echo "portable-build.sh: requires Linux (got $os_name)" >&2
  exit 1
fi
arch_name="$(uname -m)"
if [ "$arch_name" != "x86_64" ]; then
  echo "portable-build.sh: requires x86_64 (got $arch_name)" >&2
  exit 1
fi
uid_now="$(id -u)"
gid_now="$(id -g)"
if [ "$uid_now" -eq 0 ]; then
  echo "portable-build.sh: run as your desktop user, not root" >&2
  exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "portable-build.sh: docker is required for the controlled build" >&2
  exit 2
fi
if ! command -v mktemp >/dev/null 2>&1; then
  echo "portable-build.sh: mktemp is required" >&2
  exit 2
fi

script_dir="$(dirname "$0")"
repo="$(cd "$script_dir/../../.." && pwd -P)"
dockerfile="$repo/buildpython/steps/appimage/Dockerfile.portable"
inner_script="$repo/buildpython/steps/appimage/portable-inner.sh"
if [ ! -f "$repo/pyproject.toml" ]; then
  echo "portable-build.sh: missing pyproject.toml under $repo" >&2
  exit 2
fi
if [ ! -f "$dockerfile" ]; then
  echo "portable-build.sh: missing $dockerfile" >&2
  exit 2
fi
if [ ! -f "$inner_script" ]; then
  echo "portable-build.sh: missing $inner_script" >&2
  exit 2
fi

umask 077
scratch_base="${RUNNER_TEMP:-${TMPDIR:-/tmp/opencode}}"
scratch="$(mktemp -d "$scratch_base/portable-build.XXXXXX")"
cleanup() {
  rm -rf "$scratch"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP

context="$scratch/context"
mkdir -p "$context"
iid_file="$scratch/iid"

docker build --platform linux/amd64 -f "$dockerfile" --iidfile "$iid_file" "$context"

iid_raw="$(cat "$iid_file")"
iid="${iid_raw#sha256:}"
case "$iid" in
  "")
    echo "portable-build.sh: empty image id" >&2
    exit 1
    ;;
esac
if [ "${#iid}" -ne 64 ]; then
  echo "portable-build.sh: invalid image id length" >&2
  exit 1
fi
case "$iid" in
  *[!0-9a-f]*)
    echo "portable-build.sh: invalid image id characters" >&2
    exit 1
    ;;
esac

inner_path="/workspace/buildpython/steps/appimage/portable-inner.sh"

docker run --rm --platform linux/amd64 --user "$uid_now:$gid_now" --cap-drop=ALL --security-opt=no-new-privileges -e HOME=/tmp/opencode/home -e PYTHON_BIN=/opt/naga-python/bin/python3.12 -e ARCH=x86_64 -e LD_LIBRARY_PATH=/opt/naga-python/lib -e PYTHONHOME= -e PYTHONPATH= -e LD_PRELOAD= -v "$repo:/workspace" -w /workspace "$iid" bash "$inner_path" build

docker run --rm --platform linux/amd64 --user "$uid_now:$gid_now" --cap-drop=ALL --security-opt=no-new-privileges --read-only --network none --pids-limit 256 --memory 4g --cpus 2 --tmpfs /tmp/opencode:rw,nosuid,nodev,size=3G,mode=1777 -e HOME=/tmp/opencode/home -e PYTHON_BIN=/opt/naga-python/bin/python3.12 -e ARCH=x86_64 -e LD_LIBRARY_PATH=/opt/naga-python/lib -e PYTHONHOME= -e PYTHONPATH= -e LD_PRELOAD= -e TMPDIR=/tmp/opencode -v "$repo:/workspace:ro" -w /workspace "$iid" bash "$inner_path" gate

docker run --rm --platform linux/amd64 --user "$uid_now:$gid_now" --cap-drop=ALL --security-opt=no-new-privileges --read-only --network none --pids-limit 256 --memory 4g --cpus 2 --tmpfs /tmp/opencode:rw,nosuid,nodev,size=3G,mode=1777 -e HOME=/tmp/opencode/home -e PYTHON_BIN=/opt/naga-python/bin/python3.12 -e ARCH=x86_64 -e LD_LIBRARY_PATH=/opt/naga-python/lib -e PYTHONHOME= -e PYTHONPATH= -e LD_PRELOAD= -e TMPDIR=/tmp/opencode -e QT_QPA_PLATFORM=offscreen -e RELEASE_VERSION="${RELEASE_VERSION:-}" -v "$repo:/workspace:ro" -w /workspace "$iid" bash "$inner_path" check

printf '%s\n' "portable artifact verified: static ABI gate pass + Ubuntu 22.04 baseline userspace smoke pass (desktop/hardware acceptance still required)"
