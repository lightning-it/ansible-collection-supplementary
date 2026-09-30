#!/usr/bin/env bash
set -euo pipefail

readonly PROFILE_NAME="repository-quality"

fail_closed() {
  printf 'Error: %s\n' "$1" >&2
  exit 1
}

if [ "$#" -ne 1 ] || [ "$1" != "$PROFILE_NAME" ]; then
  printf 'Usage: %s %s\n' "${0##*/}" "$PROFILE_NAME" >&2
  exit 2
fi

for required_directory in scripts .lit docs docs/adr; do
  [ -d "$required_directory" ] && [ ! -L "$required_directory" ] \
    || fail_closed "required quality-policy ancestor is unsafe: $required_directory"
done

for required_path in \
  scripts/wunder-devtools-ee.sh \
  scripts/validate-quality-policy.py \
  .lit/quality-policy.yml \
  .lit/quality-policy.schema.json \
  docs/adr/mlx-10-distributed-test-ownership.md \
  docs/adr/mlx-40-lifecycle-versioning-release-evidence.md \
  docs/adr/mlx-70-prevalidated-candidate-evidence.md
do
  [ -f "$required_path" ] && [ ! -L "$required_path" ] \
    || fail_closed "required regular quality-policy input is missing: $required_path"
done

env \
  CONTAINER_HOME=/tmp/wunder \
  WUNDER_DEVTOOLS_CAP_ADD= \
  WUNDER_DEVTOOLS_DOCKER_SOCKET=disabled \
  WUNDER_DEVTOOLS_FORWARD_VAGRANT_SSH=disabled \
  WUNDER_DEVTOOLS_MOUNT_SOURCE_ROOT=disabled \
  WUNDER_DEVTOOLS_NETWORK=none \
  WUNDER_DEVTOOLS_PRIVILEGED=0 \
  WUNDER_DEVTOOLS_ROOTFS_MODE=ro \
  WUNDER_DEVTOOLS_RUN_AS_HOST_UID=1 \
  WUNDER_DEVTOOLS_RUN_AS_ROOT=0 \
  WUNDER_DEVTOOLS_WORKSPACE_MODE=ro \
  bash scripts/wunder-devtools-ee.sh \
  python3 scripts/validate-quality-policy.py .lit/quality-policy.yml
