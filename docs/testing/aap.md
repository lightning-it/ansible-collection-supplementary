# AAP Testing

AAP role tests in this collection focus on the AAP roles themselves.

Incus instance lifecycle is no longer implemented by this repository. The old
`deploy/incus` shell helpers and the protected `molecule/aap-rhel9` /
`molecule/aap-rhel10` scenarios were removed to avoid maintaining two Incus
automation paths.

Use `lit.ubuntu.incus_instance` from `ansible-collection-ubuntu` for Incus VM
creation, cloud-init SSH access, start/stop/delete handling, and generated
inventory. Then run the AAP roles against the created RHEL guest:

```yaml
- hosts: incus_hosts
  roles:
    - role: lit.ubuntu.incus_instance

- hosts: aap_hosts
  roles:
    - role: lit.rhel.rhsm
    - role: lit.rhel.repos
    - role: lit.rhel.virtual_guest
    - role: lit.rhel.podman
    - role: lit.supplementary.aap_prepare
    - role: lit.supplementary.aap_deploy
```

Keep real protected validation workflows in the consumer validation repository.
This collection should keep reusable AAP role logic and public-safe checks.

## Public-Safe Checks

Run the repository checks:

```bash
bash scripts/devtools-ansible-lint.sh
bash scripts/devtools-collection-smoke.sh
bash scripts/devtools-galaxy-verify.sh
bash scripts/devtools-molecule.sh
```

## Protected AAP Validation

Protected validation requires private inputs and infrastructure:

- trusted Incus host
- RHEL image aliases
- RHSM credentials or activation keys
- AAP setup bundle
- AAP manifest
- promoted execution environment with required certified collections

Do not run private-image or secret-backed tests on untrusted fork pull requests.
