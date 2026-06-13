# Incus AAP Workflow

These scripts provide the active local workflow for AAP development in this collection.
VM mode is the default because the AAP roles depend on guest OS behavior that is closer to a real RHEL system.

Available scripts:

- `deploy/incus/create.sh`
- `deploy/incus/inventory.sh`
- `deploy/incus/wait-for-instance.sh`
- `deploy/incus/destroy.sh`

## Image Alias Resolution

RHEL 9:

- prefer `INCUS_RHEL98_IMAGE`
- otherwise prefer `local:rhel98-ci`
- then fall back to `INCUS_RHEL9_IMAGE`
- then fall back to `local:rhel9-ci`

RHEL 10:

- prefer `INCUS_RHEL10_IMAGE`
- otherwise use `local:rhel10-ci`

## Common Usage

Create the default validated RHEL 9.8 VM:

```bash
deploy/incus/create.sh --version 9 --vm --name aap-rhel9-dev
```

Print a usable Ansible inventory:

```bash
deploy/incus/inventory.sh aap-rhel9-dev > /tmp/aap-rhel9-dev.yml
```

Wait for the instance explicitly:

```bash
deploy/incus/wait-for-instance.sh aap-rhel9-dev
```

Destroy the instance:

```bash
deploy/incus/destroy.sh aap-rhel9-dev
```

## Environment Variables

- `INCUS_RHEL98_IMAGE`
- `INCUS_RHEL9_IMAGE`
- `INCUS_RHEL10_IMAGE`
- `INCUS_SSH_PUBLIC_KEY_FILE`
- `INCUS_SSH_PRIVATE_KEY_FILE`
- `INCUS_SSH_USER`
- `INCUS_SSH_COMMON_ARGS`
- `INCUS_FQDN_SUFFIX`
- `INCUS_VM_CPU`
- `INCUS_VM_MEMORY`
- `INCUS_WAIT_TIMEOUT`

Example env files:

- `deploy/incus/examples/aap-rhel9.env`
- `deploy/incus/examples/aap-rhel10.env`

## Notes

- VM mode is the default validated path.
- Container mode is optional and intended only for fast-path experimentation with images that already provide
  systemd, cloud-init, and SSH.
- The scripts do not download private RHEL images or publish any image content.
