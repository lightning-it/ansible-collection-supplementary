# aap_deploy

Install Red Hat Ansible Automation Platform (AAP) 2.6 with the official containerized installer in
bundle mode.

## Requirements

- RHEL host with FQDN hostname.
- Dedicated non-root install user with sudo (rootless Podman model).
- RHSM registration and BaseOS/AppStream repositories when host prep is enabled.
- `ansible-core` and `podman` on target host (managed by host prep if enabled).
- `infra.aap_utilities` collection installed in the execution environment.
- Red Hat offline token for installer download API access.

## Variables

See `roles/aap_deploy/defaults/main.yml`.

Key variables:
- `aap_deploy_enabled`
- `aap_deploy_install_type` (must be `bundle`)
- `aap_deploy_topology` (`growth` or `enterprise`)
- `aap_deploy_install_user`
- `aap_deploy_install_dir`
- `rh_offline_token` (preferred input, usually seeded from Vault in inventory/playbook)
- `aap_deploy_setup_download_offline_token` (optional override; defaults to `rh_offline_token`)
- `aap_deploy_setup_download_version`
- `aap_deploy_setup_download_version_patch`
- `aap_deploy_setup_download_type`
- `aap_deploy_setup_download_containerized`
- `aap_deploy_setup_prepare_process_template`
- `aap_deploy_setup_install_force`
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
- `aap_deploy_tls_enabled`
- `aap_deploy_tls_source` (`customer_files` or `vault_pki`)
- `aap_deploy_tls_customer_files` (controller-side cert/key paths plus `ca_cert_src`)
- `aap_deploy_tls_vault_pki_mount_point`
- `aap_deploy_tls_vault_pki_services` (per-service `role_name`, `common_name`, `alt_names`, `ip_sans`)
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

Vendor-driven installer behavior:
- Role performs an early existing-install detection (marker and runtime containers).
- Marker-based skip is runtime-validated by default to avoid stale marker false positives.
- When detected, host prep, bundle handling, inventory rendering, and installer execution are skipped.
- Verification still runs (when enabled).
- Role downloads the bundle via `infra.aap_utilities.aap_setup_download`.
- Role prepares the setup workspace and renders installer inventory via `infra.aap_utilities.aap_setup_prepare`.
- Role runs the containerized installer via `infra.aap_utilities.aap_setup_install`.
- Default bundle dir is `bundle` (relative to the extracted setup directory).

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
- Admin password resolution in this role does not read or write Vault directly.

Installer TLS behavior:
- When enabled, the role stages TLS assets under `aap_deploy_tls_dir` on the managed host.
- The upstream installer receives only remote file paths (`*_tls_cert`, `*_tls_key`, `custom_ca_cert`).
- Default layout is separate cert/key pairs for gateway, controller, hub, and EDA, plus one shared CA file.
- `customer_files` copies controller-side files to the target before installer prep.
- `vault_pki` generates separate leaf certs per service/FQDN from HashiCorp Vault PKI and reuses one shared CA bundle.

## Dependencies

Requires `infra.aap_utilities` in the execution environment.

## Example Playbook

```yaml
- name: Install AAP 2.6 (growth, downloaded bundle)
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
        rh_offline_token: "{{ lookup('community.hashi_vault.vault_kv2_get', 'my/path')['secret']['rh_offline_token'] }}"
        aap_deploy_setup_download_version: "2.6"
        aap_deploy_setup_download_containerized: true
        aap_deploy_bundle_dir: bundle

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
