#!/usr/bin/env bash
set -euo pipefail

IMAGE="ghcr.io/lightning-it/wunder-devtools-ee:main"

docker run --rm \
  --entrypoint "" \
  ${ANSIBLE_EE_IMAGE:+-e ANSIBLE_EE_IMAGE} \
  ${ANSIBLE_COLLECTIONS_PATHS:+-e ANSIBLE_COLLECTIONS_PATHS} \
  -v "$PWD":/workspace \
  -w /workspace \
  "$IMAGE" "$@"
