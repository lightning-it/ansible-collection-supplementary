# Testing

This collection now uses Incus as the active local AAP development and test workflow.
Vagrant has been removed from the active path because the AAP roles need a closer match to
real RHEL behavior, including systemd, SELinux, firewalld, RHSM, and rootless Podman.

Use these docs:

- [docs/testing/aap.md](/home/rene/sources/ansible-collection-supplementary/docs/testing/aap.md) for AAP-specific workflows
- [deploy/incus/README.md](/home/rene/sources/ansible-collection-supplementary/deploy/incus/README.md) for the Incus helper scripts

Test classes:

- Public-safe checks:
  Run lint, syntax, and non-protected Molecule checks. These do not require private RHEL images,
  RHSM credentials, Red Hat credentials, or repository secrets.
- Protected RHEL checks:
  Run `molecule/aap-rhel9` and `molecule/aap-rhel10` on a trusted self-hosted machine with Incus
  installed and private image aliases preloaded.

Useful commands:

```bash
bash scripts/devtools-molecule.sh
MOLECULE_RUN_PROTECTED=true molecule test -s aap-rhel9
MOLECULE_RUN_PROTECTED=true molecule test -s aap-rhel10
```
