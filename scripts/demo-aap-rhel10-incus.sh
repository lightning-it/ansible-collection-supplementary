#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"

usage() {
  cat <<'EOF'
Usage: scripts/demo-aap-rhel10-incus.sh

Create a RHEL 10 Incus VM and run the AAP deploy playbook for an AAP 2.7
containerized bundle install.

Environment overrides:
  AAP_DEMO_INSTANCE              Instance name (default: aap-rhel10-demo)
  AAP_BUNDLE_FILE                Local AAP setup bundle (default: /srv/aap/aap-containerized-setup.tar.gz)
  AAP_DEMO_ADMIN_PASSWORD        Shared demo admin password (default: generated)
  AAP_DEMO_INSTALL_REQUIREMENTS  Install collection requirements first (default: true)
  AAP_DEMO_REUSE_INSTANCE        Reuse an existing Incus instance (default: false)
  AAP_DEMO_HOST_PREP            Run RHSM/package host prep (default: true)
  AAP_DEMO_RUN_INSTALLER         Run the AAP installer (default: true)
  AAP_DEMO_RUN_VERIFY            Run post-install verification tasks (default: true)
  RHSM_ORG_ID                    RHSM organization id for RHEL VM registration
  RHSM_ACTIVATION_KEY            RHSM activation key for RHEL VM registration
  INCUS_RHEL10_IMAGE             Incus image alias (default: local:rhel10-ci)
  INCUS_VM_CPU                   VM CPU count (default: 4)
  INCUS_VM_MEMORY                VM memory (default: 20GiB)
  INCUS_VM_ROOT_SIZE             VM root disk size (default: 70GiB)
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

generate_password() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 24
  else
    date -u "+AAPDemo-%Y%m%d%H%M%S-%N"
  fi
}

yaml_single_quote() {
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/''/g")"
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

if [ "$#" -gt 0 ]; then
  usage >&2
  exit 1
fi

require_cmd ansible-galaxy
require_cmd ansible-playbook
require_cmd incus
require_cmd python3
require_cmd ssh

cd "${repo_root}"

export INCUS_RHEL10_IMAGE="${INCUS_RHEL10_IMAGE:-local:rhel10-ci}"
export INCUS_VM_CPU="${INCUS_VM_CPU:-4}"
export INCUS_VM_MEMORY="${INCUS_VM_MEMORY:-20GiB}"
export INCUS_VM_ROOT_SIZE="${INCUS_VM_ROOT_SIZE:-70GiB}"

instance="${AAP_DEMO_INSTANCE:-aap-rhel10-demo}"
inventory_path="${AAP_DEMO_INVENTORY:-/tmp/${instance}.yml}"
vars_path="${AAP_DEMO_VARS:-/tmp/${instance}-aap-vars.yml}"
bundle_file="${AAP_BUNDLE_FILE:-/srv/aap/aap-containerized-setup.tar.gz}"
install_requirements="$(bool_value "${AAP_DEMO_INSTALL_REQUIREMENTS:-true}")"
reuse_instance="$(bool_value "${AAP_DEMO_REUSE_INSTANCE:-false}")"
host_prep="$(bool_value "${AAP_DEMO_HOST_PREP:-true}")"
run_installer="$(bool_value "${AAP_DEMO_RUN_INSTALLER:-true}")"
run_verify="$(bool_value "${AAP_DEMO_RUN_VERIFY:-true}")"
admin_password="${AAP_DEMO_ADMIN_PASSWORD:-$(generate_password)}"
admin_password_yaml="$(yaml_single_quote "${admin_password}")"

if [ "${run_installer}" = "true" ] && [ ! -f "${bundle_file}" ]; then
  echo "ERROR: AAP bundle not found: ${bundle_file}" >&2
  echo "Set AAP_BUNDLE_FILE to the local AAP 2.7 containerized setup bundle." >&2
  exit 1
fi

if ! incus_info_output="$(incus info 2>&1)"; then
  echo "ERROR: incus is installed, but no reachable Incus daemon/remote is configured." >&2
  printf '%s\n' "${incus_info_output}" >&2
  echo "Run this script on an Incus host, or configure the local incus client to use a remote Incus host." >&2
  exit 1
fi

if [ "${install_requirements}" = "true" ]; then
  ansible-galaxy collection install -r collections/requirements.yml
  ansible-galaxy collection install -r collections/requirements-rh.yml
fi

if incus info "${instance}" >/dev/null 2>&1; then
  if [ "${reuse_instance}" != "true" ]; then
    echo "ERROR: Incus instance already exists: ${instance}" >&2
    echo "Set AAP_DEMO_REUSE_INSTANCE=true to reuse it, or destroy it first." >&2
    exit 1
  fi
  deploy/incus/wait-for-instance.sh "${instance}"
else
  deploy/incus/create.sh --version 10 --vm --name "${instance}"
fi

deploy/incus/inventory.sh "${instance}" > "${inventory_path}"
chmod 0600 "${inventory_path}"

if [ "${host_prep}" = "true" ]; then
  ansible-playbook \
    -i "${inventory_path}" \
    playbooks/rhel_prepare.yml \
    -e rhel_guest_target=aap_hosts
fi

cat > "${vars_path}" <<EOF
---
aap_password_require_component_inputs: false
aap_admin_password_input: ${admin_password_yaml}

aap_deploy_topology: growth
aap_deploy_setup_download_version: "2.7"
aap_deploy_validate_certs: false
aap_deploy_manage_host_prep: ${host_prep}
aap_deploy_manage_download_unpack: ${run_installer}
aap_deploy_run_installer: ${run_installer}
aap_deploy_run_verify: ${run_verify}
EOF
chmod 0600 "${vars_path}"

export AAP_BUNDLE_FILE="${bundle_file}"

ansible-playbook \
  -i "${inventory_path}" \
  playbooks/aap_deploy.yml \
  -e @"${vars_path}"

cat <<EOF

AAP demo run complete.
  Instance: ${instance}
  Inventory: ${inventory_path}
  Vars: ${vars_path}

Destroy the VM when finished:
  deploy/incus/destroy.sh ${instance}

The destroy helper unregisters RHSM from a running guest before deleting it.
EOF
