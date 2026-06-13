#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: deploy/incus/destroy.sh INSTANCE

Force-delete a local Incus instance created for AAP development.
EOF
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: $1" >&2
    exit 1
  }
}

if [ "$#" -ne 1 ]; then
  usage >&2
  exit 1
fi

name="$1"

require_cmd incus

if ! incus info "$name" >/dev/null 2>&1; then
  echo "Instance does not exist: ${name}" >&2
  exit 0
fi

incus delete "$name" --force
echo "Destroyed Incus instance: ${name}"
