#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Usage: deploy/incus/create.sh [--version 9|10] [--vm|--container] [--name INSTANCE] [--hostname HOSTNAME]

Create a local Incus instance for AAP development.
Defaults:
  --version 9
  --vm
  --name aap-rhel<version>-<timestamp>
  --hostname INSTANCE
EOF
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: $1" >&2
    exit 1
  }
}

image_exists() {
  incus image info "$1" >/dev/null 2>&1
}

add_candidate() {
  local candidate="${1:-}"

  if [ -z "$candidate" ]; then
    return
  fi

  for existing in "${image_candidates[@]:-}"; do
    if [ "$existing" = "$candidate" ]; then
      return
    fi
  done

  image_candidates+=("$candidate")
}

select_image() {
  local version="$1"
  image_candidates=()

  case "$version" in
    9)
      add_candidate "${INCUS_RHEL98_IMAGE:-}"
      add_candidate "local:rhel98-ci"
      add_candidate "${INCUS_RHEL9_IMAGE:-}"
      add_candidate "local:rhel9-ci"
      ;;
    10)
      add_candidate "${INCUS_RHEL10_IMAGE:-}"
      add_candidate "local:rhel10-ci"
      ;;
    *)
      echo "ERROR: unsupported RHEL major version: ${version}" >&2
      exit 1
      ;;
  esac

  for candidate in "${image_candidates[@]}"; do
    if image_exists "$candidate"; then
      printf '%s\n' "$candidate"
      return
    fi
  done

  echo "ERROR: no usable Incus image alias found for RHEL ${version}." >&2
  printf 'Checked aliases:\n' >&2
  printf '  - %s\n' "${image_candidates[@]}" >&2
  exit 1
}

resolve_ssh_public_keys() {
  {
    if [ -n "${INCUS_SSH_PUBLIC_KEY:-}" ]; then
      printf '%s\n' "${INCUS_SSH_PUBLIC_KEY}"
    fi

    if [ -n "${INCUS_SSH_PUBLIC_KEY_FILE:-}" ]; then
      if [ ! -f "${INCUS_SSH_PUBLIC_KEY_FILE}" ]; then
        echo "ERROR: SSH public key file does not exist: ${INCUS_SSH_PUBLIC_KEY_FILE}" >&2
        exit 1
      fi
      sed '/^[[:space:]]*$/d' "${INCUS_SSH_PUBLIC_KEY_FILE}"
    fi
  } | awk 'NF && !seen[$0]++'
}

resolve_ssh_user() {
  printf '%s\n' "${INCUS_SSH_USER:-cloud-user}"
}

render_user_data() {
  local template_file="$1"
  local instance_name="$2"
  local instance_fqdn="$3"
  local ssh_user="$4"
  local public_keys="$5"
  local authorized_keys_yaml=""
  local key

  while IFS= read -r key; do
    if [ -n "$key" ]; then
      authorized_keys_yaml+="      - ${key}"$'\n'
    fi
  done <<< "$public_keys"

  TEMPLATE_FILE="$template_file" \
  INSTANCE_NAME="$instance_name" \
  INSTANCE_FQDN="$instance_fqdn" \
  SSH_USER="$ssh_user" \
  AUTHORIZED_KEYS_YAML="${authorized_keys_yaml%$'\n'}" \
  python3 <<'PY'
import os
import json
from pathlib import Path

template = Path(os.environ["TEMPLATE_FILE"]).read_text()
authorized_keys = [
    key.strip()
    for key in os.environ["AUTHORIZED_KEYS_YAML"].splitlines()
    if key.strip()
]
content = (
    template
    .replace("__HOSTNAME__", os.environ["INSTANCE_NAME"])
    .replace("__FQDN__", os.environ["INSTANCE_FQDN"])
    .replace("__SSH_USER__", os.environ["SSH_USER"])
    .replace("__SSH_AUTHORIZED_KEYS__", json.dumps(authorized_keys))
)
print(content, end="")
PY
}

render_network_config() {
  local mac_address="$1"

  cat <<'EOF'
version: 2
ethernets:
  incus0:
EOF
  if [ -n "$mac_address" ]; then
    cat <<EOF
    match:
      macaddress: "${mac_address}"
EOF
  fi
  cat <<'EOF'
    dhcp4: true
    dhcp6: true
    accept-ra: true
EOF
}

instance_ipv4() {
  local name="$1"

  incus list "$name" --format json | python3 -c '
import json
import sys

instances = json.load(sys.stdin)
for instance in instances:
    network = instance.get("state", {}).get("network", {})
    for iface in network.values():
        for addr in iface.get("addresses", []):
            if addr.get("family") == "inet" and addr.get("address") != "127.0.0.1":
                print(addr["address"])
                raise SystemExit(0)
raise SystemExit(1)
' 2>/dev/null || true
}

version="9"
mode="vm"
name=""
hostname=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --version)
      version="${2:-}"
      shift 2
      ;;
    --vm)
      mode="vm"
      shift
      ;;
    --container)
      mode="container"
      shift
      ;;
    --name)
      name="${2:-}"
      shift 2
      ;;
    --hostname)
      hostname="${2:-}"
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

case "$version" in
  9|10) ;;
  *)
    echo "ERROR: --version must be 9 or 10" >&2
    exit 1
    ;;
esac

case "$mode" in
  vm|container) ;;
  *)
    echo "ERROR: mode must be vm or container" >&2
    exit 1
    ;;
esac

require_cmd incus
require_cmd python3

if [ -z "$name" ]; then
  name="aap-rhel${version}-$(date -u +%Y%m%d%H%M%S)"
fi

if [ -z "$hostname" ]; then
  hostname="$name"
fi

if incus info "$name" >/dev/null 2>&1; then
  echo "ERROR: Incus instance already exists: ${name}" >&2
  exit 1
fi

image="$(select_image "$version")"
ssh_user="$(resolve_ssh_user)"
public_keys="$(resolve_ssh_public_keys)"

if [ -z "$public_keys" ]; then
  echo "ERROR: no SSH public key found. Set INCUS_SSH_PUBLIC_KEY or INCUS_SSH_PUBLIC_KEY_FILE." >&2
  exit 1
fi

if [[ "$hostname" == *.* ]]; then
  fqdn="$hostname"
else
  fqdn="${hostname}.${INCUS_FQDN_SUFFIX:-incus.local}"
fi

case "$version" in
  9) profile_file="${script_dir}/profiles/rhel9.yml" ;;
  10) profile_file="${script_dir}/profiles/rhel10.yml" ;;
esac

tmp_user_data="$(mktemp)"
tmp_network_config="$(mktemp)"
trap 'rm -f "${tmp_user_data}" "${tmp_network_config}"' EXIT
render_user_data "$profile_file" "$hostname" "$fqdn" "$ssh_user" "$public_keys" > "${tmp_user_data}"

if [ "$mode" = "vm" ]; then
  require_cmd mkisofs
  if [ ! -e /dev/kvm ]; then
    echo "ERROR: VM mode requires KVM, but /dev/kvm is not available on this host." >&2
    echo "Enable/expose hardware virtualization or use an Incus host with KVM support." >&2
    exit 1
  fi
  incus init "$image" "$name" --vm
  if [ -n "${INCUS_VM_ROOT_SIZE:-}" ]; then
    incus config device override "$name" root size="${INCUS_VM_ROOT_SIZE}"
  fi
  if [ -n "${INCUS_VM_CPU:-}" ]; then
    incus config set "$name" limits.cpu "${INCUS_VM_CPU}"
  fi
  if [ -n "${INCUS_VM_MEMORY:-}" ]; then
    incus config set "$name" limits.memory "${INCUS_VM_MEMORY}"
  fi
  mac_address="$(incus config get "$name" volatile.eth0.hwaddr)"
  render_network_config "$mac_address" > "${tmp_network_config}"
  incus config set "$name" cloud-init.user-data - < "${tmp_user_data}"
  incus config set "$name" cloud-init.network-config - < "${tmp_network_config}"
  incus config device add "$name" cloud-init disk source=cloud-init:config
else
  incus init "$image" "$name"
  if [ -n "${INCUS_CONTAINER_CPU:-}" ]; then
    incus config set "$name" limits.cpu "${INCUS_CONTAINER_CPU}"
  fi
  if [ -n "${INCUS_CONTAINER_MEMORY:-}" ]; then
    incus config set "$name" limits.memory "${INCUS_CONTAINER_MEMORY}"
  fi
  incus config set "$name" user.user-data - < "${tmp_user_data}"
fi

incus start "$name"

"${script_dir}/wait-for-instance.sh" "$name" --timeout "${INCUS_WAIT_TIMEOUT:-900}"

ip_address="$(instance_ipv4 "$name")"

echo "Instance ready."
echo "  Name: ${name}"
echo "  Hostname: ${hostname}"
echo "  Mode: ${mode}"
echo "  Image: ${image}"
echo "  FQDN: ${fqdn}"
echo "  IPv4: ${ip_address:-unknown}"
echo "  Inventory command: ${script_dir}/inventory.sh ${name}"
