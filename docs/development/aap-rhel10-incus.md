# AAP 2.7 RHEL 10 Incus Development Test

This guide reproduces the current AAP role development test for RHEL 10.

Important boundary:

- workbench is the Ansible control machine.
- `ciwkr01` is the Incus/KVM host.
- the RHEL 10 VM runs inside Incus on `ciwkr01`.

This is a development workflow for `roles/aap_deploy`. It is not a production runbook.

## Preconditions

- workbench can run Ansible from this collection checkout.
- workbench can reach `ciwkr01` through the inventory used by `modulix-automation`.
- `ciwkr01` has Incus initialized and `/dev/kvm` available.
- `ciwkr01` has a RHEL 10 Incus VM image alias.
- For the current lab, use `local:rhel10-ci-incus-ssh`.
- `sshpass` is installed on workbench when the jump host uses password auth.

The current image alias was created from the RHEL 10 qcow2 with two development adjustments:

- the qcow2 was resized by 1 GiB so Incus can move the secondary GPT header.
- a temporary `cloud-user` SSH bootstrap was baked into the development image.

## 1. Set Variables On Workbench

```bash
cd /home/rene/sources/ansible-collection-supplementary

export COLLECTION_REPO_DIR="/home/rene/sources/ansible-collection-supplementary"
export AUTOMATION_ANSIBLE_DIR="/home/rene/sources/modulix-automation/ansible"
export INVENTORY_FILE="/home/rene/sources/ansible-inventory-lit/inventories/corp/inventory.yml"

export CIWKR01_HOST="ciwkr01.prd.dmz.corp.l-it.io"
export CIWKR01_MGMT_IP="10.10.30.40"
export CIWKR01_USER="litadm"
export CIWKR01_PASS="${CIWKR01_PASS:?set CIWKR01_PASS in your shell first}"
export SSHPASS="$CIWKR01_PASS"

export TEST_VM="codex-aap-rhel10-smoke"
export TEST_DIR="/tmp/codex-aap-incus"
export INCUS_IMAGE="local:rhel10-ci-incus-ssh"
```

## 2. Check ciwkr01 Incus Access

```bash
cd "$AUTOMATION_ANSIBLE_DIR"

ANSIBLE_CONFIG=ansible.cfg ansible \
  -i "$INVENTORY_FILE" \
  "$CIWKR01_HOST" \
  -e ansible_become=false \
  -m ansible.builtin.shell \
  -a 'set -euo pipefail
hostname
id
ls -l /dev/kvm
incus info >/dev/null
incus image info local:rhel10-ci-incus-ssh >/dev/null
incus image list | sed -n "1,120p"'
```

Expected:

- user is in `incus-admin`.
- `/dev/kvm` exists.
- `local:rhel10-ci-incus-ssh` exists.

## 3. Stage Incus Helper Scripts On ciwkr01

```bash
cd "$AUTOMATION_ANSIBLE_DIR"

ANSIBLE_CONFIG=ansible.cfg ansible \
  -i "$INVENTORY_FILE" \
  "$CIWKR01_HOST" \
  -e ansible_become=false \
  -m ansible.builtin.file \
  -a "path=$TEST_DIR state=directory mode=0755"

ANSIBLE_CONFIG=ansible.cfg ansible \
  -i "$INVENTORY_FILE" \
  "$CIWKR01_HOST" \
  -e ansible_become=false \
  -m ansible.builtin.copy \
  -a "src=$COLLECTION_REPO_DIR/deploy/incus/ dest=$TEST_DIR/incus/ mode=preserve"
```

## 4. Create The RHEL 10 Incus VM On ciwkr01

```bash
cd "$AUTOMATION_ANSIBLE_DIR"

ANSIBLE_CONFIG=ansible.cfg ansible \
  -i "$INVENTORY_FILE" \
  "$CIWKR01_HOST" \
  -e ansible_become=false \
  -m ansible.builtin.shell \
  -a "set -euo pipefail
mkdir -p $TEST_DIR
if [ ! -f $TEST_DIR/id_ed25519 ]; then
  ssh-keygen -t ed25519 -N '' -f $TEST_DIR/id_ed25519 -C codex-aap-incus >/dev/null
fi
$TEST_DIR/incus/destroy.sh $TEST_VM || true
INCUS_SSH_PUBLIC_KEY_FILE=$TEST_DIR/id_ed25519.pub \
INCUS_SSH_PRIVATE_KEY_FILE=$TEST_DIR/id_ed25519 \
INCUS_RHEL10_IMAGE=$INCUS_IMAGE \
INCUS_VM_CPU=2 \
INCUS_VM_MEMORY=4GiB \
INCUS_WAIT_TIMEOUT=900 \
$TEST_DIR/incus/create.sh --version 10 --vm --name $TEST_VM"
```

## 5. Build Temporary Workbench Inventory

The temporary inventory uses workbench as the Ansible control node and jumps through `ciwkr01`
to reach the Incus guest network.

```bash
mkdir -p "$TEST_DIR"

SSHPASS="$CIWKR01_PASS" sshpass -e ssh \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  "$CIWKR01_USER@$CIWKR01_MGMT_IP" \
  "cat $TEST_DIR/id_ed25519" > "$TEST_DIR/id_ed25519"

chmod 600 "$TEST_DIR/id_ed25519"

VM_IP="$(SSHPASS="$CIWKR01_PASS" sshpass -e ssh \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  "$CIWKR01_USER@$CIWKR01_MGMT_IP" \
  "incus list $TEST_VM --format json" \
  | python3 -c 'import json,sys
d=json.load(sys.stdin)
print([a["address"] for i in d for n in i.get("state",{}).get("network",{}).values()
       for a in n.get("addresses",[])
       if a.get("family")=="inet" and a.get("address")!="127.0.0.1"][0])')"

cat > "$TEST_DIR/inventory.yml" <<EOF
all:
  children:
    aap_hosts:
      hosts:
        $TEST_VM:
          ansible_host: $VM_IP
          ansible_user: cloud-user
          ansible_become: true
          ansible_python_interpreter: /usr/bin/python3
          ansible_ssh_private_key_file: $TEST_DIR/id_ed25519
          ansible_ssh_common_args: >-
            -o StrictHostKeyChecking=no
            -o UserKnownHostsFile=/dev/null
            -o ProxyCommand="sshpass -e ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -W %h:%p $CIWKR01_USER@$CIWKR01_MGMT_IP"
EOF
```

## 6. Test Ansible Connectivity

```bash
cd "$COLLECTION_REPO_DIR"

ANSIBLE_CONFIG=ansible.cfg ansible \
  -i "$TEST_DIR/inventory.yml" \
  aap_hosts \
  -m ansible.builtin.ping
```

Expected:

```text
ping: pong
```

## 7. Run The AAP Role Smoke Test

This validates RHEL 10 targeting, role prechecks, shared AAP password resolution, and the AAP 2.7 role defaults.
It does not run host prep, bundle unpack, or the real installer.

```bash
cat > "$TEST_DIR/aap-smoke.yml" <<'EOF'
---
- name: Smoke-test aap_deploy on RHEL 10 Incus VM
  hosts: aap_hosts
  become: true
  gather_facts: true
  roles:
    - role: aap_deploy
      vars:
        aap_deploy_topology: growth
        aap_deploy_bundle_dir: /opt/aap/bundle
        aap_deploy_manage_host_prep: false
        aap_deploy_manage_download_unpack: false
        aap_deploy_run_installer: false
        aap_deploy_run_verify: false
        aap_deploy_validate_certs: false
        aap_deploy_password_active_slot: active
        aap_gateway_admin_password_input: molecule-gateway-password
        aap_controller_admin_password_input: molecule-controller-password
        aap_hub_admin_password_input: molecule-hub-password
        aap_eda_admin_password_input: molecule-eda-password
        aap_postgresql_admin_password_input: molecule-postgresql-password
EOF

ANSIBLE_CONFIG=ansible.cfg ansible-playbook \
  -i "$TEST_DIR/inventory.yml" \
  "$TEST_DIR/aap-smoke.yml"
```

Expected recap:

```text
failed=0
unreachable=0
```

## 8. Run The RHEL 10 Verifier

`molecule/aap-rhel10/verify.yml` expects Molecule's generated inventory name.
For this remote-Incus development flow, copy the temporary inventory to that expected name.

```bash
cp "$TEST_DIR/inventory.yml" "$TEST_DIR/incus-inventory.yml"

MOLECULE_EPHEMERAL_DIRECTORY="$TEST_DIR" \
ANSIBLE_CONFIG=ansible.cfg \
ansible-playbook molecule/aap-rhel10/verify.yml
```

Expected checks:

- facts are gathered from the RHEL 10 VM.
- distribution is `RedHat`.
- major version is `10`.
- `aap_deploy_setup_download_version` is `2.7`.

## 9. Full AAP Install Later

The smoke workflow above does not install AAP. A real install needs the AAP 2.7
containerized setup bundle on the control node or already staged on the managed VM.

Example:

```bash
export AAP_BUNDLE_FILE="/path/to/ansible-automation-platform-containerized-setup-bundle-2.7-*.tar.gz"
```

Then run a playbook with:

```yaml
aap_deploy_manage_host_prep: true
aap_deploy_manage_download_unpack: true
aap_deploy_run_installer: true
aap_deploy_run_verify: true
```

Host prep may require RHSM registration and repositories inside the RHEL 10 VM.

## 10. Cleanup

Destroy the VM on `ciwkr01`:

```bash
cd "$AUTOMATION_ANSIBLE_DIR"

ANSIBLE_CONFIG=ansible.cfg ansible \
  -i "$INVENTORY_FILE" \
  "$CIWKR01_HOST" \
  -e ansible_become=false \
  -m ansible.builtin.shell \
  -a "$TEST_DIR/incus/destroy.sh $TEST_VM"
```

Remove temporary workbench files:

```bash
rm -rf "$TEST_DIR"
```

## Troubleshooting

Check VM state on `ciwkr01`:

```bash
cd "$AUTOMATION_ANSIBLE_DIR"

ANSIBLE_CONFIG=ansible.cfg ansible \
  -i "$INVENTORY_FILE" \
  "$CIWKR01_HOST" \
  -e ansible_become=false \
  -m ansible.builtin.shell \
  -a "set -euo pipefail
incus list $TEST_VM
incus info $TEST_VM | sed -n '1,140p'
incus console $TEST_VM --show-log | tail -n 160 || true"
```

Check SSH through the same path as Ansible:

```bash
ANSIBLE_CONFIG=ansible.cfg ansible \
  -i "$TEST_DIR/inventory.yml" \
  aap_hosts \
  -m ansible.builtin.shell \
  -a 'hostname; cat /etc/os-release; id'
```

If Incus fails with `sgdisk --move-second-header`, the qcow2 probably has no free space after
the final partition. Use a resized copy for Incus import instead of the original download.
