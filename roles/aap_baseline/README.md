# aap_baseline

Prepare and verify the AAP baseline host contract from inventory.

## Purpose

`lit.supplementary.aap_baseline` verifies and optionally prepares the minimal
host contract required before AAP local execution can run.

It is intentionally not a full enterprise OS baseline role. Customer-owned
RHEL, Satellite, RHSM, and repository configuration can stay outside Modulix;
this role only checks or prepares the AAP-specific substrate that the later
runbooks need.

## Supported Platforms

- Machine A/controller: Linux with Ansible and SSH.
- Target: Red Hat Enterprise Linux 9 or 10.

## Actions

- `local_setup`: prepare Machine A directories and automation checkout.
- `verify`: verify SSH, sudo, package/repository visibility, and expected RHEL
  release before changing the target.
- `prepare`: create AAP substrate directories and, when explicitly enabled,
  install required packages or resize storage.
- `check`: verify the prepared host contract after `prepare`.

## Key Variables

- `aap_action` / `aap_baseline_action`: selected action.
- `aap_fqdn`: public AAP FQDN.
- `aap_ansible_host`: SSH target, either FQDN or IP address.
- `aap_setup_user`: setup account, defaults to `svc_ansible`.
- `aap_install_user`: runtime/install account, defaults to `svc_aap`.
- `aap_baseline_manage_packages`: install baseline packages when `true`.
- `aap_baseline_manage_storage`: grow the configured disk/LVM layout when
  `true`.
- `aap_baseline_expected_rhel_major`: optional RHEL major assertion.
- `aap_baseline_setup_public_key`: optional key to authorize for EE
  self-connections.

## Security

- The setup and runtime accounts must be separate.
- The setup account must have passwordless sudo for automation.
- Service-owned directories are created with restrictive permissions where they
  contain state or secrets.

## Example

```yaml
- name: Prepare AAP baseline
  hosts: aap_baseline_targets
  gather_facts: false
  roles:
    - role: lit.supplementary.aap_baseline
      vars:
        aap_action: prepare
        aap_fqdn: aap03.example.com
        aap_setup_user: svc_ansible
        aap_install_user: svc_aap
        aap_baseline_manage_packages: false
```

## Outputs

The role creates or verifies:

- `/appl` substrate directories.
- `aap_appl_root` local-execution directories.
- Optional authorized key for the setup account.
- Optional package and storage baseline when explicitly enabled.

## Molecule Coverage

Baseline behavior is covered through runbook-level local execution scenarios and
target integration tests. Storage growth is intentionally not exercised by
lightweight Molecule because it requires a disposable block-device layout.

## Known Limitations

- RHSM/repository management is not owned by this role.
- Storage growth assumes the configured disk, partition, and LVM layout match
  the target environment.
