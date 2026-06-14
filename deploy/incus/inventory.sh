#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: deploy/incus/inventory.sh INSTANCE [--group GROUP] [--host-alias HOST]

Print a YAML inventory for an Incus instance created by deploy/incus/create.sh.
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

if [ "$#" -lt 1 ]; then
  usage >&2
  exit 1
fi

name="$1"
group="aap_hosts"
host_alias=""
shift

while [ "$#" -gt 0 ]; do
  case "$1" in
    --group)
      group="${2:-}"
      shift 2
      ;;
    --host-alias)
      host_alias="${2:-}"
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

require_cmd incus
require_cmd python3

if ! incus info "$name" >/dev/null 2>&1; then
  echo "ERROR: Incus instance not found: ${name}" >&2
  exit 1
fi

ip_address="$(instance_ip_address "$name")"
if [ -z "$ip_address" ]; then
  echo "ERROR: could not determine usable IP address for ${name}" >&2
  exit 1
fi

ssh_user="${INCUS_SSH_USER:-cloud-user}"
private_key_file="$(resolve_ssh_private_key_file)"
ssh_common_args="${INCUS_SSH_COMMON_ARGS:--o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null}"
inventory_host="${host_alias:-$name}"

cat <<EOF
all:
  children:
    ${group}:
      hosts:
        ${inventory_host}:
          ansible_host: "${ip_address}"
          ansible_user: ${ssh_user}
          ansible_become: true
          ansible_python_interpreter: /usr/bin/python3
          ansible_ssh_private_key_file: ${private_key_file}
          ansible_ssh_common_args: ${ssh_common_args}
EOF
