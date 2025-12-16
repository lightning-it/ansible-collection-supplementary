#!/usr/bin/env bash
set -euo pipefail

IMAGE="${WUNDER_DEVTOOLS_EE_IMAGE:-ghcr.io/lightning-it/wunder-devtools-ee:v1.1.0}"
CONTAINER_HOME="${CONTAINER_HOME:-/tmp/wunder}"
HOST_HOME_CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/wunder-devtools-ee/home"

mkdir -p "$HOST_HOME_CACHE"

DOCKER_ARGS=(
  -v "$PWD":/workspace
  -w /workspace
  -e HOME="${CONTAINER_HOME}"
  -v "$HOST_HOME_CACHE":"${CONTAINER_HOME}"
)

# Mount Docker-Socket
if [ -S /var/run/docker.sock ]; then
  DOCKER_ARGS+=(-v /var/run/docker.sock:/var/run/docker.sock)
  DOCKER_ARGS+=(--user "$(id -u):$(id -g)")
  DOCKER_ARGS+=(--group-add 0)

  socket_gid="$(stat -c %g /var/run/docker.sock 2>/dev/null || stat -f %g /var/run/docker.sock 2>/dev/null || true)"
  if [ -n "${socket_gid:-}" ]; then
    DOCKER_ARGS+=(--group-add "$socket_gid")
  fi
fi

# On Linux runners, provide host.docker.internal → host-gateway
if [ "$(uname -s)" = "Linux" ]; then
  DOCKER_ARGS+=(--add-host=host.docker.internal:host-gateway)
fi

docker run --rm \
  --entrypoint "" \
  "${DOCKER_ARGS[@]}" \
  ${ANSIBLE_COLLECTIONS_PATHS:+-e ANSIBLE_COLLECTIONS_PATHS} \
  ${ANSIBLE_ROLES_PATH:+-e ANSIBLE_ROLES_PATH} \
  "$IMAGE" "$@"
