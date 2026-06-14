#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: deploy/incus/wait-for-instance.sh INSTANCE [--timeout SECONDS]

Wait for an Incus instance to be running, reachable over SSH, and past cloud-init.
EOF
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: $1" >&2
    exit 1
  }
}

resolve_ssh_private_key_file() {
  if [ -n "${INCUS_SSH_PRIVATE_KEY_FILE:-}" ]; then
    printf '%s\n' "${INCUS_SSH_PRIVATE_KEY_FILE}"
    return
  fi

  local candidate
  for candidate in \
    "${HOME}/.ssh/id_ed25519" \
    "${HOME}/.ssh/id_ecdsa" \
    "${HOME}/.ssh/id_rsa"; do
    if [ -f "$candidate" ]; then
      printf '%s\n' "$candidate"
      return
    fi
  done

  echo "ERROR: no SSH private key found. Set INCUS_SSH_PRIVATE_KEY_FILE." >&2
  exit 1
}

instance_status() {
  local name="$1"

  incus list "$name" -c s --format csv 2>/dev/null | head -n 1 | tr -d '\r'
}

instance_ip_address() {
  local name="$1"

  incus list "$name" --format json | python3 -c '
import json
import sys

instances = json.load(sys.stdin)
addresses = []
for instance in instances:
    network = instance.get("state", {}).get("network", {})
    for iface in network.values():
        for addr in iface.get("addresses", []):
            family = addr.get("family")
            address = addr.get("address", "")
            if family == "inet" and address != "127.0.0.1":
                addresses.append((0, address))
            elif family == "inet6" and address and not address.startswith(("::1", "fe80:")):
                addresses.append((1, address))
if addresses:
    print(sorted(addresses)[0][1])
    raise SystemExit(0)
raise SystemExit(1)
' 2>/dev/null || true
}

name="${1:-}"
timeout="900"

if [ -z "$name" ]; then
  usage >&2
  exit 1
fi
shift

while [ "$#" -gt 0 ]; do
  case "$1" in
    --timeout)
      timeout="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

case "$timeout" in
  ''|*[!0-9]*)
    echo "ERROR: --timeout must be an integer" >&2
    exit 1
    ;;
esac

require_cmd incus
require_cmd python3
require_cmd ssh

if ! incus info "$name" >/dev/null 2>&1; then
  echo "ERROR: Incus instance not found: ${name}" >&2
  exit 1
fi

ssh_user="${INCUS_SSH_USER:-cloud-user}"
private_key_file="$(resolve_ssh_private_key_file)"
ssh_opts=(
  -o BatchMode=yes
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
  -o ConnectTimeout=5
  -i "${private_key_file}"
)

deadline=$((SECONDS + timeout))

while [ "${SECONDS}" -lt "${deadline}" ]; do
  status="$(instance_status "$name")"
  if [ "$status" = "RUNNING" ]; then
    break
  fi
  sleep 2
done

if [ "$(instance_status "$name")" != "RUNNING" ]; then
  echo "ERROR: instance did not reach RUNNING state within ${timeout}s: ${name}" >&2
  exit 1
fi

ip_address=""
while [ "${SECONDS}" -lt "${deadline}" ]; do
  ip_address="$(instance_ip_address "$name")"
  if [ -n "$ip_address" ]; then
    break
  fi
  sleep 2
done

if [ -z "$ip_address" ]; then
  echo "ERROR: no usable IP address detected for ${name} within ${timeout}s" >&2
  exit 1
fi

while [ "${SECONDS}" -lt "${deadline}" ]; do
  if ssh "${ssh_opts[@]}" "${ssh_user}@${ip_address}" true >/dev/null 2>&1; then
    break
  fi
  sleep 5
done

if ! ssh "${ssh_opts[@]}" "${ssh_user}@${ip_address}" true >/dev/null 2>&1; then
  echo "ERROR: SSH did not become ready for ${name} (${ip_address}) within ${timeout}s" >&2
  exit 1
fi

ssh "${ssh_opts[@]}" "${ssh_user}@${ip_address}" \
  'if command -v cloud-init >/dev/null 2>&1; then sudo cloud-init status --wait || cloud-init status --wait || true; fi'

echo "Instance is ready: ${name} (${ip_address})"
