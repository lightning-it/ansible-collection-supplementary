#!/usr/bin/env bash
# Repository-local deterministic hooks use the centrally pinned runtime.
set -euo pipefail

if [ "$#" -eq 0 ]; then
  echo 'Usage: devtools-local-quality.sh <validator> [arguments...]' >&2
  exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

# Do not inherit opt-ins intended for other (integration/deployment) workloads.
# No host tool fallback, package installation, daemon socket or external egress.
export WUNDER_DEVTOOLS_WORKSPACE_MODE=ro
export WUNDER_DEVTOOLS_ROOTFS_MODE=ro
export WUNDER_DEVTOOLS_NETWORK=none
export WUNDER_DEVTOOLS_PRIVILEGED=0
export WUNDER_DEVTOOLS_RUN_AS_ROOT=0
export WUNDER_DEVTOOLS_RUN_AS_HOST_UID=1
export WUNDER_DEVTOOLS_DOCKER_SOCKET=disabled
export WUNDER_DEVTOOLS_MOUNT_SOURCE_ROOT=disabled
export WUNDER_DEVTOOLS_FORWARD_VAGRANT_SSH=disabled
export WUNDER_DEVTOOLS_CAP_ADD=''
export CONTAINER_HOME=/tmp/wunder

exec bash "${script_dir}/wunder-devtools-ee.sh" bash -lc '
  set -euo pipefail
  # HOME is supplied as fresh private container tmpfs by the managed wrapper.
  # Never use the host home or writable workspace for validator state.
  export RUNNER_TEMP="${HOME}/runner-temp"
  export RUFF_CACHE_DIR="${HOME}/ruff-cache"
  export MYPY_CACHE_DIR="${HOME}/mypy-cache"
  export XDG_CACHE_HOME="${HOME}/cache"
  mkdir -p "$RUNNER_TEMP" "$RUFF_CACHE_DIR" "$MYPY_CACHE_DIR" "$XDG_CACHE_HOME"
  exec "$@"
' -- "$@"
