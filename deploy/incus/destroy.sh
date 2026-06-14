#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: deploy/incus/destroy.sh INSTANCE

Force-delete a local Incus instance created for AAP development.

By default, a running RHEL guest is unregistered from RHSM before deletion.
Set INCUS_RHSM_UNREGISTER_ON_DESTROY=false to skip that step.
Set INCUS_RHSM_UNREGISTER_STRICT=false to delete even when unregister fails.
EOF
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: $1" >&2
    exit 1
  }
}

bool_value() {
  case "${1:-}" in
    true|TRUE|yes|YES|1|on|ON) printf 'true\n' ;;
    false|FALSE|no|NO|0|off|OFF) printf 'false\n' ;;
    *)
      echo "ERROR: invalid boolean value: ${1:-<empty>}" >&2
      exit 1
      ;;
  esac
}

instance_status() {
  local instance_name="$1"

  incus info "$instance_name" | awk -F': ' '/^Status:/ { print $2; exit }'
}

unregister_rhsm() {
  local instance_name="$1"
  local strict="$2"
  local status output

  status="$(instance_status "$instance_name")"
  if [ "$status" != "RUNNING" ]; then
    echo "RHSM unregister skipped because instance is not running: ${instance_name} (${status})" >&2
    if [ "$strict" = "true" ]; then
      echo "Start the instance first, or set INCUS_RHSM_UNREGISTER_ON_DESTROY=false to skip." >&2
      exit 1
    fi
    return
  fi

  # shellcheck disable=SC2016
  if ! output="$(incus exec "$instance_name" -- /bin/sh -eu -c '
if ! command -v subscription-manager >/dev/null 2>&1; then
  exit 0
fi

cleanup_needed=false
if subscription-manager identity >/dev/null 2>&1; then
  subscription-manager unregister
  cleanup_needed=true
fi

if [ -e /etc/pki/consumer/cert.pem ]; then
  cleanup_needed=true
fi

if find /etc/pki/entitlement -type f -name "*.pem" -print -quit 2>/dev/null | grep -q .; then
  cleanup_needed=true
fi

if [ "$cleanup_needed" = "true" ]; then
  subscription-manager clean
fi
' 2>&1)"; then
    printf '%s\n' "$output" >&2
    echo "ERROR: RHSM unregister failed for ${instance_name}." >&2
    if [ "$strict" = "true" ]; then
      echo "Set INCUS_RHSM_UNREGISTER_STRICT=false to delete anyway." >&2
      exit 1
    fi
    return
  fi

  if [ -n "$output" ]; then
    printf '%s\n' "$output"
  fi
  echo "RHSM unregister/clean completed or was not needed for: ${instance_name}"
}

if [ "$#" -ne 1 ]; then
  usage >&2
  exit 1
fi

name="$1"
rhsm_unregister="$(bool_value "${INCUS_RHSM_UNREGISTER_ON_DESTROY:-true}")"
rhsm_unregister_strict="$(bool_value "${INCUS_RHSM_UNREGISTER_STRICT:-true}")"

require_cmd incus

if ! incus info "$name" >/dev/null 2>&1; then
  echo "Instance does not exist: ${name}" >&2
  exit 0
fi

if [ "$rhsm_unregister" = "true" ]; then
  unregister_rhsm "$name" "$rhsm_unregister_strict"
fi

incus delete "$name" --force
echo "Destroyed Incus instance: ${name}"
