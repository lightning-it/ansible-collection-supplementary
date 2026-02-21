# aap_deploy

Install Red Hat Ansible Automation Platform (AAP) 2.6 with the official containerized installer in disconnected
bundle mode.

## Requirements

- RHEL host with FQDN hostname.
- Dedicated non-root install user with sudo (rootless Podman model).
- RHSM registration and BaseOS/AppStream repositories when host prep is enabled.
- `ansible-core` and `podman` on target host (managed by host prep if enabled).
- AAP containerized setup bundle archive (`.tar.gz`) available on target host or local Ansible mount.

## Variables

See `roles/aap_deploy/defaults/main.yml`.

Key variables:
- `aap_deploy_enabled`
- `aap_deploy_install_type` (must be `bundle`)
- `aap_deploy_topology` (`growth` or `enterprise`)
- `aap_deploy_install_user`
- `aap_deploy_install_dir`
- `aap_deploy_setup_archive_src`
- `aap_deploy_bundle_dir` (path containing `/bundle`)
- `aap_deploy_redis_mode` (`standalone` or `cluster`)
- `aap_deploy_redis_hosts` (required when `aap_deploy_redis_mode=cluster`, at least 6 hosts)
- `aap_deploy_postgresql_admin_username` (default: `postgres`)
- `aap_deploy_gateway_pg_host` / `aap_deploy_controller_pg_host` / `aap_deploy_hub_pg_host` / `aap_deploy_eda_pg_host`
- `aap_deploy_gateway_pg_password` / `aap_deploy_controller_pg_password`
- `aap_deploy_hub_pg_password` / `aap_deploy_eda_pg_password`
- `aap_deploy_gateway_admin_password`
- `aap_deploy_controller_admin_password`
- `aap_deploy_hub_admin_password`
- `aap_deploy_eda_admin_password`
- `aap_deploy_postgresql_admin_password`
- `aap_admin_password` (shared fallback when per-component values are not all set)
- `aap_admin_passwords_source_of_truth` (`inventory` or `vault`)
- `aap_admin_passwords_generate`
- `aap_admin_passwords_read_from_vault`
- `aap_admin_passwords_write_to_vault`
- `aap_admin_passwords_vault_addr`
- `aap_admin_passwords_vault_kv_mount`
- `aap_admin_passwords_vault_kv_path`
- `aap_deploy_manage_host_prep`
- `aap_deploy_manage_download_unpack`
- `aap_deploy_run_installer`
- `aap_deploy_run_verify`
- `aap_deploy_skip_if_installed`
- `aap_deploy_enforce_min_mem_check` (default: `true`)
- `aap_deploy_min_mem_mb` (default: `15000`, approximately 16GB)

Bundle archive source behavior:
- Role checks target path `aap_deploy_setup_archive_src`.
- Role checks local Ansible paths:
  - `/runner/project/<bundle-file>`
  - `/runner/project/.artifacts/<bundle-file>`
- If missing everywhere, role fails with actionable download/staging steps.
- Default archive path is `/opt/aap/aap-containerized-setup.tar.gz`.
- Default bundle dir is `/opt/aap/setup/bundle`.

Installer admin password behavior:
- Passwords for gateway/controller/hub/eda/postgresql are resolved independently.
- Resolution order is: explicit variable -> Vault KV2 (source=`vault`) -> local cache (lab fallback) -> generated password.
- Resolution is handled by shared role `aap` (foundational-style).
- Default source of truth is `inventory` and generation is disabled by default.
- For inventory source of truth, each `aap_deploy_*_admin_password` can be set individually.
- Any missing component password falls back to `aap_admin_password`.
- When Vault write is enabled and configured, resolved values are stored at:
  `aap_admin_passwords_vault_kv_mount/aap_admin_passwords_vault_kv_path`.
- Backward-compatible `aap_deploy_passwords_*` variables are still accepted.

## Dependencies

None.

## Example Playbook

```yaml
- name: Install AAP 2.6 (growth, disconnected bundle)
  hosts: aap_hosts
  become: true
  gather_facts: true
  roles:
    - role: lit.supplementary.aap_deploy
      vars:
        aap_deploy_install_type: bundle
        aap_deploy_topology: growth
        aap_deploy_install_user: aap
        aap_deploy_install_dir: /opt/aap
        aap_deploy_setup_archive_src: /opt/aap/aap-containerized-setup.tar.gz
        aap_deploy_bundle_dir: /opt/aap/setup/bundle

        # Password management (source of truth = Vault)
        aap_admin_passwords_source_of_truth: vault
        aap_admin_passwords_generate: true
        aap_admin_passwords_vault_addr: "{{ vault_address }}"
        aap_admin_passwords_vault_kv_mount: "{{ vault_engine_mount_point | default('stage-2c') }}"
        aap_admin_passwords_vault_kv_path: "{{ inventory_hostname }}/aap/deploy/admin_passwords"
        # Optional explicit override for one component password:
        # aap_deploy_controller_admin_password: "set-me-explicitly"
```

## License

GPL-3.0-only

## Author

Lightning IT
