#!/usr/bin/env bash
set -euo pipefail

actionlint_image="${ACTIONLINT_IMAGE:-docker.io/rhysd/actionlint:latest}"

have_docker=false
have_podman=false

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  have_docker=true
fi

if command -v podman >/dev/null 2>&1 && podman info >/dev/null 2>&1; then
  have_podman=true
fi

if [ "${have_docker}" = true ]; then
  exec docker run --rm -v "$PWD":/repo -w /repo "${actionlint_image}"
fi

if [ "${have_podman}" = true ]; then
  exec podman run --rm -v "$PWD":/repo:Z -w /repo "${actionlint_image}"
fi

if [ "${CI:-false}" = "true" ] || [ "${GITHUB_ACTIONS:-false}" = "true" ]; then
  echo "ERROR: actionlint requires docker or podman in CI." >&2
  exit 1
fi

echo "Skipping actionlint locally because neither docker nor podman is available." >&2
