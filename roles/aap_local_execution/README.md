# aap_local_execution

Drive AAP local-execution actions from Machine A and on the staged AAP host.

## Purpose

`lit.supplementary.aap_local_execution` is the controller for disconnected AAP
rollout flows where a workstation or workbench ("Machine A") prepares artifacts
and then executes the real AAP runbooks on the target host through an execution
environment.

The role keeps customer-facing guides thin: operators provide inventory values
and select `aap_action`; this role performs validation, local artifact handling,
payload transfer, runtime staging, inventory generation, and execution
environment command assembly.

## Supported Platforms

- Machine A: Linux host with Ansible, SSH, tar, and optionally Podman.
- AAP target: Red Hat Enterprise Linux 9 or 10 prepared for AAP local execution.

The target setup account must be `svc_ansible` and the AAP runtime/install user
must be `svc_aap`.

## Common Actions

- `validate`: check local values, artifacts, and secret backend access.
- `prepare_machine_a`: create local directories, checkout automation, and stage
  local support files.
- `seed_rh_offline_token`: store `rh_offline_token` in HashiCorp Vault defaults.
- `transfer_payload`: transfer prepared local payload to the AAP target.
- `stage_runtime`: unpack source, stage artifacts, configure Podman storage, and
  generate the remote AAP inventory.
- `artifacts`, `base_preflight`, `tls`, `deploy`, `status`: run the matching AAP
  runbooks inside the configured execution environment.

## Key Variables

- `aap_action` / `aap_local_action`: selected action.
- `aap_fqdn`: public AAP FQDN used for URLs and TLS.
- `aap_ansible_host`: SSH target, either FQDN or IP address.
- `aap_inventory_host`: short internal inventory alias.
- `aap_secret_backend`: `hashicorp_vault` or `ansible_vault`.
- `machine_a_appl_root`: local working state, defaults to `~/aap-work`.
- `machine_a_export_root`: local export/artifact tree, defaults to
  `~/aap-export`.
- `aap_appl_root`: remote local-execution root, defaults to `/appl/aap-local`.
- `modulix_run_ee_image`: execution environment image.
- `modulix_run_ee_digest`: optional `sha256:...` digest. Machine A still pulls
  and exports `modulix_run_ee_image`; target-side pulls and EE runs use the
  immutable `repository@digest` reference (without a tag) when this value is
  set.
- `aap_ee_transfer_enabled`: copy the EE image from Machine A when `true`; pull
  it from the target-side registry when `false`.
- `aap_ee_archive_force`: recreate the local EE archive even when it already
  exists.
- `aap_source_archive_force`: recreate the source archive during payload
  transfer. Defaults to `true` to preserve current rollout behavior.

## Security

- Secret files are written with `0600`.
- Ansible Vault generated inventory files are written with `0600` and protected
  with `no_log`.
- Vault tokens are never printed and are transferred only when the HashiCorp
  backend is selected.
- HashiCorp Vault mode does not create or pass an Ansible Vault password file.
- EE commands use the project's dedicated `aap-local.cfg`, which has no global
  Vault password-file default. Ansible Vault mode passes its password file
  explicitly.
- Vault TLS verification defaults to enabled. Set `vault_validate_certs: false`
  only as an explicit, temporary opt-out. The target host CA trust is mounted
  read-only into the execution environment and exposed through
  `REQUESTS_CA_BUNDLE`; override `aap_host_ca_trust_dir` or
  `aap_requests_ca_bundle` only for a nonstandard RHEL trust layout.
- The fingerprint-verified Machine A known-hosts file is transferred to the
  target and mounted with the secret directory. Generated SSH connections use
  `StrictHostKeyChecking=yes`, and EE runs force Ansible host-key checking on.
- The execution environment receives only the environment variables needed for
  the runbook action.

## Example

```yaml
- name: Prepare Machine A
  hosts: localhost
  gather_facts: false
  roles:
    - role: lit.supplementary.aap_local_execution
      vars:
        aap_action: prepare_machine_a
        aap_fqdn: aap03.example.com
        aap_inventory_host: aap03
        aap_ansible_host: 192.0.2.10
        modulix_run_ee_image: registry.example.com/ee-aap:v1.21.2
```

## Outputs

The role creates or updates:

- Machine A state under `machine_a_appl_root`.
- Machine A export tree under `machine_a_export_root`.
- Remote local-execution state under `aap_appl_root`.
- Generated AAP inventory under the remote automation checkout.

## Molecule Coverage

Top-level Molecule scenarios cover the shared AAP roles. Heavy product install
coverage is intentionally handled by runbook-level integration tests because it
requires a real RHEL host, AAP bundle, manifest, registry access, and secrets.

## Known Limitations

- Full AAP installation is not simulated in lightweight Molecule scenarios.
- `transfer_payload` intentionally keeps source archive recreation enabled by
  default so copied source changes are not missed during active development.
