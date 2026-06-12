# aap_deploy

Install Red Hat Ansible Automation Platform (AAP) with the official containerized installer in
bundle mode. This role targets AAP 2.7 containerized deployments.

## Requirements

- RHEL host with FQDN hostname.
- Dedicated non-root install user with sudo (rootless Podman model).
- RHSM registration and BaseOS/AppStream repositories when host prep is enabled.
- `ansible-core`, `python3`, and `podman` on target host (managed by host prep if enabled).
- `infra.aap_utilities` collection installed in the execution environment.
- Red Hat offline token for installer download API access.
- Enough local storage for bundle copy and extraction. Red Hat documents a minimum 60 GB
  total local disk, 15 GB installation directory when separately partitioned, and 10 GB
  temporary directory for offline/bundled installations. Size customer bundle workflows larger.

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
- `aap_deploy_automationmetrics_enabled` (default: `true`)
- `aap_deploy_setup_prep_inv_nodes_extra`
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
- `aap_deploy_tls_customer_files` (controller-side cert/key paths or inline
  `cert_content`/`key_content`, plus `ca_cert_src` or `ca_cert_content`)
- `aap_deploy_tls_vault_pki_mount_point`
- `aap_deploy_tls_vault_pki_services` (per-service `role_name`, `common_name`, `alt_names`, `ip_sans`)
- `aap_deploy_manage_host_prep`
- `aap_deploy_manage_rhsm_repos`
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

AAP 2.7 automation metrics inventory:

```yaml
aap_deploy_setup_download_version: "2.7"
aap_deploy_automationmetrics_enabled: true
aap_deploy_growth_automationmetrics_host: "{{ ansible_fqdn | default(inventory_hostname) }}"
```

AAP 2.7 containerized installer preflight requires an `automationmetrics`
inventory group. Growth topology uses `aap_deploy_growth_automationmetrics_host`;
enterprise topology uses `aap_deploy_enterprise_automationmetrics_hosts`.

Use `aap_deploy_setup_prep_inv_nodes_extra` to merge additional installer
inventory groups into the generated `aap_setup_prep_inv_nodes` map.

Expected single-host inventory groups rendered for AAP 2.7 growth topology:

```ini
[automationcontroller]
aap.example.com

[automationmetrics]
aap.example.com

[database]
aap.example.com
```

The role fails early when neither `aap_deploy_automationmetrics_enabled` nor an
explicit `automationmetrics` entry in `aap_deploy_setup_prep_inv_nodes_extra` is set.

RHEL 10 host prep:
- AAP 2.7 supports RHEL 10 containerized installs.
- Required RHSM repository IDs are generated from
  `ansible_distribution_major_version`, so RHEL 10 resolves to
  `rhel-10-for-<arch>-baseos-rpms` and `rhel-10-for-<arch>-appstream-rpms`.
- Red Hat documents `ansible-core` from RHEL AppStream for installation on RHEL 10.
  Host prep installs `ansible-core`, `python3`, and `podman`.

Satellite or baseline-managed repositories:

```yaml
aap_deploy_manage_host_prep: true
aap_deploy_manage_rhsm_repos: false
```

Use `aap_deploy_manage_rhsm_repos: false` on systems where repository
configuration is already handled externally, such as by Satellite, a platform
baseline, or local repo files. Host preparation remains enabled, including user
setup, sudoers, lingering, systemd manager startup, repository usability
validation with `dnf repolist`, and package installation. Only
subscription-manager registration checks and RHSM repository enablement are
skipped.

Bundle source handling:
- The role autodetects `aap-containerized-setup.tar.gz` and
  `ansible-automation-platform-containerized-setup-bundle-*.tar.gz` in the
  project root or `.artifacts`.
- For GitHub release assets or other artifact stores, reassemble split assets on
  the controller before running the role. Do not rely on the role to join split files.
- A stable customer layout is:

```yaml
aap_deploy_setup_archive_src: "{{ aap_deploy_local_project_root }}/files/aap/aap-containerized-setup.tar.gz"
aap_deploy_setup_archive_path: "{{ aap_deploy_install_dir }}/aap-containerized-setup.tar.gz"
```

Large bundle copy and temporary space:
- Ansible copies modules and transfer payloads through `ansible_remote_tmp`.
- If the SSH user's home filesystem is small, set a larger remote temp path in
  inventory, for example:

```yaml
ansible_remote_tmp: /appl/ansible-tmp
```

Ensure the remote temp path, `aap_deploy_install_dir`, and setup extraction path
have enough free space for the compressed bundle and extracted installer.

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
- `aap_deploy_tls_enabled` defaults to `false` and `aap_deploy_tls_source`
  defaults to `customer_files`; Vault PKI is not read unless
  `aap_deploy_tls_source: vault_pki` is explicitly set.
- A single customer certificate/key pair can be reused for gateway, controller,
  hub, and EDA when the certificate SANs cover every FQDN handed to the installer.
- For bootstrap or self-signed deployments, prefer `customer_files` with explicit
  cert/key paths or inline `cert_content`/`key_content`, plus a CA certificate.

Controller license manifest:
- License activation is handled by the companion `lit.supplementary.aap_cac`
  role through `aap_cac_controller_license_manifest_content`.
- Provide the manifest as base64 content from inventory or a secret backend.
- Do not commit real `manifest.zip` or `manifest.zip.b64` files.

Example:

```yaml
aap_cac_controller_license_manifest_content: >-
  {{ lookup('ansible.builtin.file', playbook_dir ~ '/files/aap/manifest.zip.b64') }}
```

Troubleshooting:
- `You must have a host set in the [automationmetrics] section`: keep
  `aap_deploy_automationmetrics_enabled: true`, or provide the group through
  `aap_deploy_setup_prep_inv_nodes_extra`.
- `No space left on device` during bundle copy: set `ansible_remote_tmp` to a
  filesystem with enough free space and verify `aap_deploy_install_dir`.
- `Overall Status: Not registered` on Satellite/baseline systems: keep
  `aap_deploy_manage_host_prep: true` and set
  `aap_deploy_manage_rhsm_repos: false`.

Local validation:

```bash
ansible-playbook tests/aap_deploy_inventory_nodes.yml
```

## Dependencies

Requires `infra.aap_utilities` in the execution environment.

## Example Playbook

```yaml
- name: Install AAP 2.7 (growth, downloaded bundle)
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
        aap_deploy_setup_download_version: "2.7"
        aap_deploy_automationmetrics_enabled: true
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
