# AAP Development Agent Guide

Scope: AAP development work for `roles/aap_deploy`, `molecule/aap-rhel10`,
`deploy/incus`, and `docs/development/aap-rhel10-incus.md`.

This guide is only for AAP role development. Production runbooks belong in the
automation/inventory repositories.

## Development Boundary

1. Workbench is the Ansible control node.
2. `ciwkr01` is the Incus/KVM host.
3. RHEL 10 test VMs run inside Incus on `ciwkr01`, not on workbench.
4. Use Ansible ad-hoc commands for checks on `ciwkr01` and the guest VM.
5. Do not reintroduce a parallel devtools container path for Incus. Incus is
   tested on the machine that provides Incus/KVM.
6. Do not use Fedora images for this workflow. Use RHEL, UBI, or Ubuntu only
   where image choice is needed.
7. Keep RHEL base images unregistered. Cloud-init owns boot identity and SSH
   access only; Ansible owns RHSM registration and unregister.

## AAP 2.7 Role Rules

1. `aap_deploy` supports disconnected bundle installs only.
2. Keep `aap_deploy_setup_download_version` pinned to `"2.7"` for RHEL 10 AAP
   development unless the user explicitly asks for a version change.
3. Do not add entitlement-gated Red Hat collections to `galaxy.yml`.
   Keep Automation Hub-only requirements in the workspace/consumer overlay.
4. Keep all role-owned variables prefixed with `aap_deploy_`.
5. The role must render an AAP 2.7 `[automationmetrics]` inventory group for
   both growth and enterprise topologies.
6. Growth topology must validate:
   - gateway host
   - controller host
   - hub host
   - EDA host
   - automation metrics host
   - PostgreSQL host
7. Enterprise topology must validate non-empty host lists for:
   - gateway
   - controller
   - hub
   - EDA
   - automation metrics
   - PostgreSQL
8. Render the AAP 2.7 automation metrics PostgreSQL variables:
   - `automationmetrics_pg_host`
   - `automationmetrics_pg_password`
   - `automationmetrics_controller_read_pg_host`
   - `automationmetrics_controller_read_pg_password`
9. Default automation metrics PostgreSQL host/password values should map from
   the existing PostgreSQL/controller effective values instead of creating a
   separate unrelated secret model.
10. Keep `acl` in the RHEL host-prep package list. The upstream installer can
    fail while becoming the rootless `aap` user if POSIX ACL tooling is missing.
11. Run the AAP-side RHEL prepare playbook before real AAP install work when
    the VM needs RHSM repositories. It must compose `lit.rhel.rhsm`,
    `lit.rhel.repos`, and `lit.rhel.virtual_guest` explicitly. Do not bake RHSM
    registration into the image.

## Bundle Handling

1. The real AAP containerized setup bundle is private and must never be tracked.
2. Store local bundles under `.artifacts/` and exclude that directory through
   `.git/info/exclude`, not repository `.gitignore`, unless the user asks for a
   tracked ignore rule.
3. When downloading Red Hat signed URLs, quote the whole URL. Unquoted `&`
   characters can produce a small HTML error file instead of the bundle.
4. Validate downloaded bundles before using them:
   - size should be multiple GiB for the full containerized setup bundle.
   - `tar -tzf` or the role archive validation must succeed.
5. Keep the role able to find a bundle from:
   - explicit local control-node path
   - project root
   - project `.artifacts/`
   - already staged target path

## Incus Test VM Rules

1. Full AAP 2.7 install testing needs more than smoke-test sizing.
2. Use at least this sizing for full installer runs:
   - 4 vCPU
   - 20 GiB memory
   - 70 GiB root disk
3. `deploy/incus/create.sh` must support `INCUS_VM_ROOT_SIZE` and apply it with
   `incus config device override <name> root size=<size>`.
4. If the guest partition does not grow automatically after an Incus root disk
   resize, grow it inside the guest with `growpart` and `xfs_growfs`.
5. The current RHEL 10 development image assumption is documented in
   `docs/development/aap-rhel10-incus.md`; update that file and
   `deploy/incus/README.md` together when image assumptions change.
6. `/dev/kvm` is required for VM-based Incus testing. Container-only Incus tests
   do not need KVM, but the AAP RHEL 10 workflow is VM-based.

## RHEL Registration Rules

1. Use `lit.rhel.rhsm` from `/home/rene/sources/ansible-collection-rhel` for
   RHSM lifecycle management.
2. Use `rhsm_state=present` after boot to register runtime VMs.
3. Use `lit.rhel.repos` to enable required RHEL repositories.
4. Use `lit.rhel.virtual_guest` for reusable VM guest packages and services.
5. Use `rhsm_state=absent` during teardown before deleting VMs.
6. Read RHSM credentials from inventory or environment variables:
   - `RHSM_ORG_ID`
   - `RHSM_ACTIVATION_KEY`
7. Do not store RHSM credentials in the image, docs, generated inventory, or
   committed vars files.
8. `deploy/incus/destroy.sh` must unregister/clean RHSM by default before
   deleting running RHEL guests.
9. Do not recreate generic RHEL registration or repository roles in this
   collection.

## Verification Rules

1. For script changes, run:
   - `shellcheck deploy/incus/create.sh deploy/incus/destroy.sh deploy/incus/inventory.sh deploy/incus/wait-for-instance.sh`
2. For repository hygiene, run:
   - `git diff --check`
3. For changed YAML, run yamllint on YAML files only. Do not pass Markdown files
   to yamllint.
4. Avoid parallel devtools container lint runs that mount the same repository
   with Podman `:Z`; SELinux relabeling can cause transient permission errors.
5. Run ansible-lint through the repository devtools script when role logic
   changes.
6. A successful full install must show:
   - upstream installer recap with `failed=0`
   - outer role play recap with `failed=0`
   - role container assertion passed
   - no exited AAP containers
   - 24 running containers for the tested growth install
7. Run Molecule verify against the generated Incus inventory after the full
   install. Use `MOLECULE_AAP_FULL_INSTALL=true` when the install marker should
   be asserted.

## Documentation Rules

1. Keep development steps in `docs/development/aap-rhel10-incus.md`.
2. Keep copy/paste commands free of secrets; read secrets from environment
   variables.
3. Make the control-node versus Incus-host boundary explicit in every new AAP
   development procedure.
4. Document what was tested, including the VM host, image alias, VM sizing,
   bundle version, and verification commands.
5. Do not turn development documentation into a production runbook.
