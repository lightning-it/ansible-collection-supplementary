#!/usr/bin/env bash
set -euo pipefail

renovate_image="${RENOVATE_IMAGE:-docker.io/renovate/renovate:latest}"

have_docker=false
have_podman=false

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  have_docker=true
fi

if command -v podman >/dev/null 2>&1 && podman info >/dev/null 2>&1; then
  have_podman=true
fi

if [ "${have_docker}" = true ]; then
  exec docker run --rm -v "$PWD":/repo -w /repo "${renovate_image}" renovate-config-validator
fi

if [ "${have_podman}" = true ]; then
  exec podman run --rm -v "$PWD":/repo:Z -w /repo "${renovate_image}" renovate-config-validator
fi

if [ "${CI:-false}" = "true" ] || [ "${GITHUB_ACTIONS:-false}" = "true" ]; then
  echo "ERROR: renovate-config-validator requires docker or podman in CI." >&2
  exit 1
fi

echo "Skipping renovate-config-validator locally because neither docker nor podman is available." >&2
