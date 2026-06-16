# AAP Testing With Incus

## Why Incus Replaced Vagrant

Vagrant is no longer the active local development path for the AAP roles in this collection.
The AAP deployment and operations path depends on real RHEL guest behavior such as:

- systemd and lingering user services
- SELinux
- firewalld
- RHSM repositories
- rootless Podman
- cloud-init and SSH boot readiness

Incus VMs are now the default local workflow because they fit those needs better on a Remote-SSH Linux lab machine.

## Supported Targets

- Red Hat Enterprise Linux 9 and 10 only
- RHEL 9.8 is the primary validated target today
- RHEL 10 support is structurally implemented for any trusted environment that has a usable RHEL 10 Incus image alias

## Remote-SSH Lab Machine Preparation

Prepare the trusted Linux machine with:

- `incus`
- `ansible-playbook`
- `molecule`
- an SSH keypair for `cloud-user`
- preloaded local Incus aliases for RHEL images

Recommended image aliases:

- `local:rhel98-ci`
- `local:rhel9-ci`
- `local:rhel10-ci`

See `deploy/incus/README.md` for creating the local `rhel10-ci` image alias
from Incus image artifacts or a standalone RHEL cloud qcow2.

Override aliases when needed:

- `INCUS_RHEL98_IMAGE`
- `INCUS_RHEL9_IMAGE`
- `INCUS_RHEL10_IMAGE`

Optional helper env files:

- `source deploy/incus/examples/aap-rhel9.env`
- `source deploy/incus/examples/aap-rhel10.env`

Install the public/community collection requirements first:

```bash
ansible-galaxy collection install -r collections/requirements.yml
```

Protected AAP install workflows also require the Red Hat AAP utility collection
set pinned in `collections/requirements-rh.yml`:

```bash
ansible-galaxy collection install -r collections/requirements-rh.yml
```

## Local AAP Development Workflow

RHEL 9.8 VM workflow:

```bash
deploy/incus/create.sh --version 9 --vm --name aap-rhel9-dev
deploy/incus/inventory.sh aap-rhel9-dev > /tmp/aap-rhel9-dev.yml
ansible-playbook -i /tmp/aap-rhel9-dev.yml playbooks/aap_deploy.yml
deploy/incus/destroy.sh aap-rhel9-dev
```

RHEL 10 VM workflow:

```bash
INCUS_RHEL10_IMAGE=local:rhel10-ci deploy/incus/create.sh --version 10 --vm --name aap-rhel10-dev
deploy/incus/inventory.sh aap-rhel10-dev > /tmp/aap-rhel10-dev.yml
ansible-playbook -i /tmp/aap-rhel10-dev.yml playbooks/aap_deploy.yml
deploy/incus/destroy.sh aap-rhel10-dev
```

The Incus helper inventory targets the `aap_hosts` group used by `playbooks/aap_deploy.yml`.
For AAP EDA tests, keep the guest hostname short. If the Incus instance name is
long because it includes a run ID, pass `--hostname` to `deploy/incus/create.sh`
and the same short name as `--host-alias` to `deploy/incus/inventory.sh`.

For registered RHEL test VMs, keep the base image unregistered and prepare each
runtime VM idempotently after boot. The playbook composes `lit.rhel.rhsm`,
`lit.rhel.repos`, and `lit.rhel.virtual_guest`:

```bash
export RHSM_ORG_ID="..."
export RHSM_ACTIVATION_KEY="..."
ansible-playbook -i /tmp/aap-rhel10-dev.yml playbooks/rhel_prepare.yml \
  -e rhel_guest_target=aap_hosts
```

Before deleting a registered VM, unregister it:

```bash
ansible-playbook -i /tmp/aap-rhel10-dev.yml playbooks/rhel_teardown.yml \
  -e rhel_guest_target=aap_hosts
deploy/incus/destroy.sh aap-rhel10-dev
```

`deploy/incus/destroy.sh` also attempts RHSM unregister/clean from a running
guest before deletion, so direct helper usage keeps the same lifecycle.

## Molecule Workflows

Protected RHEL 9.8 path:

```bash
MOLECULE_RUN_PROTECTED=true molecule test -s aap-rhel9
```

Protected RHEL 10 path:

```bash
MOLECULE_RUN_PROTECTED=true molecule test -s aap-rhel10
```

Full installer runs are optional and require a private local AAP setup bundle:

```bash
export AAP_BUNDLE_FILE=/srv/aap/aap-containerized-setup.tar.gz
export MOLECULE_AAP_FULL_INSTALL=true
MOLECULE_RUN_PROTECTED=true molecule test -s aap-rhel9
```

## Installer Temp Environment Validation

Use this lightweight Incus diagnostic when validating that
`aap_deploy_install_environment` reaches the installer task. It does not require
an AAP bundle and does not run the full vendor installer.

```bash
scripts/test-aap-install-temp-incus
```

Defaults:

- `INCUS_IMAGE=images:rockylinux/9/cloud`
- `INCUS_INSTANCE=aap27-temp-test-<pid>`
- container mode

Useful overrides:

```bash
INCUS_IMAGE=local:rhel10-ci INCUS_VM=true scripts/test-aap-install-temp-incus
KEEP_INCUS=1 scripts/test-aap-install-temp-incus
```

The helper intentionally starts with restrictive `/appl/ansible-tmp`
permissions, uses `lit.foundational.ansible_remote_tmp` to repair the general
Ansible module staging directory, then runs the same
`roles/aap_deploy/tasks/35_installer_environment.yml` diagnostic used by
`aap_deploy` and asserts:

```text
TMPDIR=/appl/tmp
TEMP=/appl/tmp
TMP=/appl/tmp
tempfile.gettempdir()=/appl/tmp
```

## AAP 2.7 RHEL 10 Demo Script

For a local end-to-end AAP 2.7 demo on RHEL 10:

```bash
export AAP_BUNDLE_FILE=/srv/aap/aap-containerized-setup.tar.gz
scripts/demo-aap-rhel10-incus.sh
```

The script installs `collections/requirements.yml` and
`collections/requirements-rh.yml`, creates or reuses a RHEL 10 Incus VM, writes a
temporary inventory and vars file under `/tmp`, runs `playbooks/rhel_prepare.yml`
when host prep is enabled, and runs `playbooks/aap_deploy.yml`.
Run it from an environment that already has the `incus` CLI and a reachable
Incus daemon or remote. The selected Incus remote must provide a RHEL 10 image
alias such as `local:rhel10-ci`.

Useful overrides:

```bash
AAP_DEMO_INSTANCE=aap-rhel10-dev \
AAP_DEMO_REUSE_INSTANCE=true \
AAP_DEMO_HOST_PREP=false \
scripts/demo-aap-rhel10-incus.sh
```

To exercise the workflow through the devtools execution environment, make sure
the devtools image includes `incus` and that its `$HOME/.config/incus` points to
the intended Incus remote:

```bash
bash scripts/wunder-devtools-ee.sh bash -lc \
  'AAP_DEMO_INSTALL_REQUIREMENTS=false AAP_DEMO_RUN_INSTALLER=false AAP_DEMO_RUN_VERIFY=false ./scripts/demo-aap-rhel10-incus.sh'
```

For a real devtools-container run, `AAP_BUNDLE_FILE` and the Incus client config
must point at paths visible inside the devtools container, such as
`/workspace/...` or `/tmp/wunder/...`.

Without `MOLECULE_AAP_FULL_INSTALL=true`, the protected scenarios stay on the public-safe side of the role flow:
they validate RHEL targeting, SSH reachability, role prechecks, password resolution inputs, and the Incus orchestration layer.

## Public-Safe vs Protected

Public-safe:

- lint
- syntax
- non-protected Molecule scenarios
- no private RHEL images
- no RHSM credentials
- no AAP bundle

Protected:

- trusted self-hosted runner or trusted lab machine only
- Incus installed and initialized
- local RHEL image aliases already loaded
- optional private AAP bundle for real installer runs
- optional RHSM access when `aap_deploy_manage_host_prep=true`

Do not run private-image or secret-backed tests on untrusted fork pull requests.

## Troubleshooting

Incus:

- `incus list`
- `incus info <instance>`
- `incus console <instance>`

Cloud-init:

- `deploy/incus/wait-for-instance.sh <instance>`
- `ssh cloud-user@<ip> sudo cloud-init status --wait`

SSH:

- confirm the local private key matches `INCUS_SSH_PUBLIC_KEY_FILE`
- rerun `deploy/incus/inventory.sh <instance>` after the VM receives an IP

DNF / RHSM:

- `ansible -i <inventory> aap_hosts -m ansible.builtin.command -a 'subscription-manager status' -b`
- `ansible -i <inventory> aap_hosts -m ansible.builtin.command -a 'subscription-manager repos --list-enabled' -b`
- if you do not want RHSM checks, keep `aap_deploy_manage_host_prep=false` and
  skip `playbooks/rhel_prepare.yml`

SELinux:

- `ssh cloud-user@<ip> getenforce`
- review target host AVCs when Podman or staged files behave unexpectedly

firewalld:

- `ssh cloud-user@<ip> sudo systemctl status firewalld`
- confirm any HTTPS verification checks match the exposed guest network path

AAP role failures:

- start with `roles/aap/tasks/assert.yml`
- then inspect `roles/aap_deploy/tasks/assert.yml`
- for full installer runs, inspect `/opt/aap/setup` and Podman logs inside the guest
