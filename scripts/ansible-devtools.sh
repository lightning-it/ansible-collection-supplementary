#!/usr/bin/env bash
set -euo pipefail

IMAGE="quay.io/ansible/creator-ee:latest"

docker run --rm \
  -v "$PWD":/workspace \
  -w /workspace \
  "$IMAGE" "$@"
