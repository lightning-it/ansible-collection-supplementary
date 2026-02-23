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
- `aap_deploy_gateway_admin_password_effective`
- `aap_deploy_controller_admin_password_effective`
- `aap_deploy_hub_admin_password_effective`
- `aap_deploy_eda_admin_password_effective`
- `aap_deploy_postgresql_admin_password_effective`
- `aap_deploy_manage_host_prep`
- `aap_deploy_manage_download_unpack`
- `aap_deploy_run_installer`
- `aap_deploy_run_verify`
- `aap_deploy_skip_if_installed`
- `aap_deploy_skip_if_installed_require_runtime` (default: `true`)
- `aap_deploy_skip_if_installed_runtime_min_matching_containers` (default: `1`)
- `aap_deploy_skip_if_runtime_active`
- `aap_deploy_runtime_probe_all_containers` (default: `true`, uses `podman ps -a`)
- `aap_deploy_runtime_name_regex` (default: `.*(automation|ansible|aap).*`)
- `aap_deploy_runtime_min_matching_containers` (default: `1`)
- `aap_deploy_enforce_min_mem_check` (default: `true`)
- `aap_deploy_min_mem_mb` (default: `15000`, approximately 16GB)

Bundle archive source behavior:
- Role performs an early existing-install detection (marker and runtime containers).
- Marker-based skip is runtime-validated by default to avoid stale marker false positives.
- When detected, host prep, bundle handling, inventory rendering, and installer execution are skipped.
- Verification still runs (when enabled).
- Preferred source is local runner dir:
  - `/runner/project/<bundle-file>`
  - Role copies it to target install path `aap_deploy_setup_archive_path` (default: `/opt/aap/aap-containerized-setup.tar.gz`)
  - Installer always uses target path.
- Role checks local Ansible paths:
  - `/runner/project/.artifacts/<bundle-file>`
- If local runner file is absent, role falls back to:
  - pre-staged target destination path (`aap_deploy_setup_archive_path`)
  - pre-staged target source path (`aap_deploy_setup_archive_src`)
- If missing everywhere, role fails with actionable staging steps.
- Role validates staged archive before unpack:
  - minimum size guard (`aap_deploy_validate_archive_min_size_bytes`, default `100000000`)
  - optional SHA256 verification when `aap_deploy_setup_archive_checksum` is set
  - tar.gz readability check (`aap_deploy_validate_archive_format`, default `true`)
- Default archive path is `/opt/aap/aap-containerized-setup.tar.gz`.
- Default bundle dir is `/opt/aap/setup/bundle`.
- Recommended for disconnected portability: keep the bundle pre-staged on the target host at `/opt/aap/aap-containerized-setup.tar.gz`.

Installer admin password behavior:
- Passwords for gateway/controller/hub/eda/postgresql are resolved independently.
- Resolution is handled by shared role `aap`.
- Source of truth is inventory input only.
- Define inventory inputs with:
  - `aap_gateway_admin_password_input`
  - `aap_controller_admin_password_input`
  - `aap_hub_admin_password_input`
  - `aap_eda_admin_password_input`
  - `aap_postgresql_admin_password_input`
- Inputs can be plain strings or slot mappings (`active`/`next`) selected by:
  - `aap_password_active` (alias)
  - `aap_password_active_slot` (canonical)
- Backend references must be resolved in inventory (for example lookup/get-or-create), not in role code.
- Role code does not read or write Vault directly.

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

        # Password inputs (inventory source of truth)
        aap_password_active: active
        aap_password_active_slot: active
        aap_gateway_admin_password_input: "{{ lookup('my_secret_backend_get_or_create', 'aap/gateway/admin') }}"
        aap_controller_admin_password_input: "{{ lookup('my_secret_backend_get_or_create', 'aap/controller/admin') }}"
        aap_hub_admin_password_input: "{{ lookup('my_secret_backend_get_or_create', 'aap/hub/admin') }}"
        aap_eda_admin_password_input: "{{ lookup('my_secret_backend_get_or_create', 'aap/eda/admin') }}"
        aap_postgresql_admin_password_input: "{{ lookup('my_secret_backend_get_or_create', 'aap/postgresql/admin') }}"
```

## License

GPL-3.0-only

## Author

Lightning IT
