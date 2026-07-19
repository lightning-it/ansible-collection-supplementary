#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  wunder-container-run.sh <container-engine-args...>

Behavior:
  - prefers podman when available
  - falls back to docker
  - if docker is used, auto-falls back to rootless podman socket when present
EOF
}

fail_closed() {
  local msg="$1"
  echo "Error: ${msg}" >&2
  exit 1
}

if [ "$#" -eq 0 ]; then
  usage >&2
  exit 2
fi

sanitize_docker_host_env() {
  if [[ "${DOCKER_HOST:-}" == unix://* ]]; then
    host_sock="${DOCKER_HOST#unix://}"
    if [ ! -S "$host_sock" ]; then
      unset DOCKER_HOST
    fi
  fi
}

docker_usable() {
  command -v docker >/dev/null 2>&1 || return 1
  sanitize_docker_host_env
  docker info >/dev/null 2>&1
}

podman_usable() {
  command -v podman >/dev/null 2>&1 || return 1
  podman info >/dev/null 2>&1
}

ENGINE="${WUNDER_CONTAINER_ENGINE:-}"
if [ -z "$ENGINE" ]; then
  if podman_usable; then
    ENGINE="podman"
  elif docker_usable; then
    ENGINE="docker"
  else
    fail_closed "no usable container engine found (docker/podman not running or unreachable)"
  fi
fi

case "$ENGINE" in
  podman|docker) ;;
  *)
    fail_closed "unsupported engine '$ENGINE' (use podman|docker)"
    ;;
esac

if [ "$ENGINE" = "docker" ]; then
  command -v docker >/dev/null 2>&1 || fail_closed "docker command not found"
else
  command -v podman >/dev/null 2>&1 || fail_closed "podman command not found"
fi

if [ "$ENGINE" = "docker" ]; then
  sanitize_docker_host_env

  # Fallback for Docker client environments without docker daemon:
  # use rootless podman socket if available.
  if [ -z "${DOCKER_HOST:-}" ]; then
    podman_sock="/run/user/$(id -u)/podman/podman.sock"
    if [ -S "$podman_sock" ]; then
      export DOCKER_HOST="unix://$podman_sock"
    fi
  fi
fi

exec "$ENGINE" "$@"
