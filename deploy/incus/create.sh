#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Usage: deploy/incus/create.sh [--version 9|10] [--vm|--container] [--name INSTANCE]

Create a local Incus instance for AAP development.
Defaults:
  --version 9
  --vm
  --name aap-rhel<version>-<timestamp>
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

resolve_ssh_public_key_file() {
  if [ -n "${INCUS_SSH_PUBLIC_KEY_FILE:-}" ]; then
    printf '%s\n' "${INCUS_SSH_PUBLIC_KEY_FILE}"
    return
  fi

  local candidate
  for candidate in \
    "${HOME}/.ssh/id_ed25519.pub" \
    "${HOME}/.ssh/id_ecdsa.pub" \
    "${HOME}/.ssh/id_rsa.pub"; do
    if [ -f "$candidate" ]; then
      printf '%s\n' "$candidate"
      return
    fi
  done

  echo "ERROR: no SSH public key found. Set INCUS_SSH_PUBLIC_KEY_FILE." >&2
  exit 1
}

resolve_ssh_user() {
  printf '%s\n' "${INCUS_SSH_USER:-cloud-user}"
}

render_user_data() {
  local template_file="$1"
  local instance_name="$2"
  local instance_fqdn="$3"
  local ssh_user="$4"
  local public_key="$5"
  local escaped_key

  escaped_key="$(printf '%s' "$public_key" | sed -e 's/[\/&]/\\&/g')"

  sed \
    -e "s/__HOSTNAME__/${instance_name}/g" \
    -e "s/__FQDN__/${instance_fqdn}/g" \
    -e "s/__SSH_USER__/${ssh_user}/g" \
    -e "s/__SSH_PUBLIC_KEY__/${escaped_key}/g" \
    "$template_file"
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

if incus info "$name" >/dev/null 2>&1; then
  echo "ERROR: Incus instance already exists: ${name}" >&2
  exit 1
fi

image="$(select_image "$version")"
ssh_user="$(resolve_ssh_user)"
pubkey_file="$(resolve_ssh_public_key_file)"
public_key="$(tr -d '\n' < "$pubkey_file")"

if [ -z "$public_key" ]; then
  echo "ERROR: SSH public key file is empty: ${pubkey_file}" >&2
  exit 1
fi

if [[ "$name" == *.* ]]; then
  fqdn="$name"
else
  fqdn="${name}.${INCUS_FQDN_SUFFIX:-incus.local}"
fi

case "$version" in
  9) profile_file="${script_dir}/profiles/rhel9.yml" ;;
  10) profile_file="${script_dir}/profiles/rhel10.yml" ;;
esac

tmp_user_data="$(mktemp)"
trap 'rm -f "${tmp_user_data}"' EXIT
render_user_data "$profile_file" "$name" "$fqdn" "$ssh_user" "$public_key" > "${tmp_user_data}"

if [ "$mode" = "vm" ]; then
  if [ ! -e /dev/kvm ]; then
    echo "ERROR: VM mode requires KVM, but /dev/kvm is not available on this host." >&2
    echo "Enable/expose hardware virtualization or use an Incus host with KVM support." >&2
    exit 1
  fi
  incus init "$image" "$name" --vm
  if [ -n "${INCUS_VM_CPU:-}" ]; then
    incus config set "$name" limits.cpu "${INCUS_VM_CPU}"
  fi
  if [ -n "${INCUS_VM_MEMORY:-}" ]; then
    incus config set "$name" limits.memory "${INCUS_VM_MEMORY}"
  fi
else
  incus init "$image" "$name"
  if [ -n "${INCUS_CONTAINER_CPU:-}" ]; then
    incus config set "$name" limits.cpu "${INCUS_CONTAINER_CPU}"
  fi
  if [ -n "${INCUS_CONTAINER_MEMORY:-}" ]; then
    incus config set "$name" limits.memory "${INCUS_CONTAINER_MEMORY}"
  fi
fi

incus config set "$name" user.user-data - < "${tmp_user_data}"
incus start "$name"

"${script_dir}/wait-for-instance.sh" "$name" --timeout "${INCUS_WAIT_TIMEOUT:-900}"

ip_address="$(instance_ipv4 "$name")"

echo "Instance ready."
echo "  Name: ${name}"
echo "  Mode: ${mode}"
echo "  Image: ${image}"
echo "  FQDN: ${fqdn}"
echo "  IPv4: ${ip_address:-unknown}"
echo "  Inventory command: ${script_dir}/inventory.sh ${name}"
