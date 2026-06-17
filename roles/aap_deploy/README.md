# aap_deploy

Install Red Hat Ansible Automation Platform (AAP) 2.7 with the official containerized installer in
bundle mode.

## Requirements

- Red Hat Enterprise Linux 9 or 10 host with FQDN hostname.
- Dedicated non-root install user with sudo (rootless Podman model).
- RHSM registration and BaseOS/AppStream repositories when host prep is enabled.
  For ephemeral Incus VMs, keep the base image unregistered and run
  `playbooks/rhel_prepare.yml` before this role. That playbook composes
  `lit.rhel.rhsm`, `lit.rhel.repos`, and `lit.rhel.virtual_guest`.
- `ansible-core`, `git`, `podman`, `rsync`, `tar`, and `unzip` on target host
  (managed by host prep if enabled).
- `infra.aap_utilities` collection installed in the execution environment.
- A local AAP containerized setup bundle on the control node for real installer runs.
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
- `aap_deploy_setup_download_version` (fixed: `"2.7"`)
- `aap_deploy_setup_download_containerized`
- `aap_deploy_setup_prepare_process_template`
- `aap_deploy_setup_install_force`
- `aap_deploy_install_environment`
- `aap_deploy_debug_install_environment`
- `aap_deploy_manage_install_tmp_dir`
- `aap_deploy_install_tmp_dir`
- `aap_deploy_bundle_dir` (path containing `/bundle`)
- `aap_deploy_installer_runner` (`native` or `vendor`, default: `native`)
- `aap_deploy_installer_wait`
- `aap_deploy_installer_async_jid_path`
- `aap_deploy_installer_async_timeout`
- `aap_deploy_installer_async_retries`
- `aap_deploy_installer_async_delay`
- `aap_deploy_installer_log_dir`
- `aap_deploy_installer_diagnostics_enabled`
- `aap_deploy_installer_diagnostics_log_tail_lines`
- `aap_deploy_redis_mode` (`standalone` or `cluster`)
- `aap_deploy_redis_hosts` (required when `aap_deploy_redis_mode=cluster`, at least 6 hosts)
- `aap_deploy_growth_automationmetrics_host`
- `aap_deploy_enterprise_automationmetrics_hosts`
- `aap_deploy_automationmetrics_pg_host`
- `aap_deploy_automationmetrics_pg_database`
- `aap_deploy_automationmetrics_pg_username`
- `aap_deploy_automationmetrics_pg_password`
- `aap_deploy_automationmetrics_controller_read_pg_username`
- `aap_deploy_automationmetrics_controller_read_pg_password`
- `aap_deploy_automationmetrics_secret_key`
- `aap_deploy_automationmetrics_resource_server`
- `aap_deploy_setup_prep_inv_nodes_extra`
- `aap_deploy_gateway_main_url` (optional installer `gateway_main_url`)
- `aap_deploy_gateway_nginx_http_port` / `aap_deploy_gateway_nginx_https_port`
- `aap_deploy_envoy_http_port` / `aap_deploy_envoy_https_port`
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
- `aap_deploy_manage_podman_storage`
- `aap_deploy_podman_graphroot`
- `aap_deploy_podman_runroot`
- `aap_deploy_enforce_min_mem_check` (default: `true`)
- `aap_deploy_min_mem_mb` (default: `15000`, approximately 16GB)
- `aap_deploy_growth_inventory_connection` (default: `local`)
- `aap_deploy_growth_inventory_hostvars_extra`
- `aap_deploy_enterprise_inventory_hostvars_extra`
- `aap_deploy_growth_automationmetrics_host`
- `aap_deploy_enterprise_automationmetrics_hosts`

Installer behavior:
- Role performs an early existing-install detection (marker and runtime containers).
- Marker-based skip is runtime-validated by default to avoid stale marker false positives.
- When detected, host prep, bundle handling, inventory rendering, and installer execution are skipped.
- Verification still runs (when enabled).
- Role expects a controller-side bundle path and copies it to the managed host.
- Role prepares the setup workspace and renders installer inventory via `infra.aap_utilities.aap_setup_prepare`.
- By default, role runs the prepared containerized installer command directly
  with controlled async status polling. Set `aap_deploy_installer_runner:
  vendor` to use `infra.aap_utilities.aap_setup_install` for compatibility.
- For CI or other orchestrators that cannot hold one Ansible polling task open
  for the full installer runtime, set `aap_deploy_installer_wait: false`.
  The role starts the native installer asynchronously, writes the async job id to
  `aap_deploy_installer_async_jid_path`, skips the install marker, and skips
  verification for that run. The orchestrator must poll the async job id with
  short Ansible calls, fail on a non-zero installer return code, and run
  verification after the async job finishes successfully.
- Role writes the installer Ansible log below `aap_deploy_installer_log_dir`.
- On installer failure, role prints redacted diagnostics before returning failure.
- Default bundle dir is `bundle` (relative to the extracted setup directory).

## Automation metrics service

```yaml
aap_deploy_setup_download_version: "2.7"
aap_deploy_growth_automationmetrics_host: "{{ ansible_fqdn | default(inventory_hostname) }}"
```

AAP 2.7 containerized installer preflight requires an `automationmetrics`
inventory group and metrics service database variables. The role always
generates `[automationmetrics]` and the required `automationmetrics_*`
installer variables.

Growth topology runs metrics on `aap_deploy_growth_automationmetrics_host` and
sets `automationmetrics_pg_host` to the selected PostgreSQL/database host by
default. Enterprise topology builds the group from
`aap_deploy_enterprise_automationmetrics_hosts`.

Default/customer-overridable metrics settings:

```yaml
aap_deploy_automationmetrics_pg_host: "{{ ansible_fqdn | default(inventory_hostname) }}"
aap_deploy_automationmetrics_pg_database: automationmetrics
aap_deploy_automationmetrics_pg_username: automationmetrics
aap_deploy_automationmetrics_pg_password: "{{ aap_postgresql_admin_password_input }}"
aap_deploy_automationmetrics_controller_read_pg_password: "{{ aap_postgresql_admin_password_input }}"
```

For external or custom database layouts, override:

```yaml
aap_deploy_automationmetrics_pg_host: db.example.com
aap_deploy_automationmetrics_pg_password: "{{ vault_metrics_pg_password }}"
aap_deploy_automationmetrics_controller_read_pg_password: "{{ vault_metrics_controller_read_password }}"
aap_deploy_automationmetrics_secret_key: "{{ vault_metrics_secret_key }}"
aap_deploy_automationmetrics_resource_server: "{{ vault_metrics_resource_server }}"
```

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

The role validates that the selected metrics host list is non-empty before
rendering the installer inventory.

After the preparation step, verify the generated inventory with:

```bash
grep -nE "automationmetrics|automationmetrics_pg_host|automationmetrics_pg_password|automationmetrics_controller_read_pg_password" /appl/aap/setup/*/inventory
```

Expected output includes `[automationmetrics]`, `automationmetrics_pg_host`,
`automationmetrics_pg_password`, and
`automationmetrics_controller_read_pg_password`.

RHEL 10 host prep:
- AAP 2.7 supports RHEL 10 containerized installs.
- This role is 2.7-only and fails fast when
  `aap_deploy_setup_download_version` is changed to another version.
- Required RHSM repository IDs are generated from
  `ansible_distribution_major_version`, so RHEL 10 resolves to
  `rhel-10-for-<arch>-baseos-rpms` and `rhel-10-for-<arch>-appstream-rpms`.
- Red Hat documents `ansible-core` from RHEL AppStream for installation on RHEL 10.
  Host prep installs the packages required by the wrapper role and the upstream
  `infra.aap_utilities.aap_setup_prepare` role.

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
- Preferred enterprise flow: use `lit.supplementary.aap_prepare` before this
  role to download/copy/check the protected setup bundle onto the managed host.
- This role still supports direct local bundle fallback for compatibility, but
  artifact store integration belongs in `aap_prepare`.
- For GitHub release assets or other artifact stores, reassemble split assets
  before running the role. Do not rely on the role to join split files.
- A stable customer layout is:

```yaml
aap_deploy_artifact_dir: "{{ aap_deploy_local_project_root }}/.artifacts"
aap_deploy_setup_archive_path: "{{ aap_deploy_install_dir }}/aap-containerized-setup.tar.gz"
```

Customer baseline/Satellite example:

```yaml
aap_deploy_install_dir: /appl/aap
aap_deploy_install_user: aap
aap_deploy_install_user_home: /home/aap
aap_deploy_manage_podman_storage: true
aap_deploy_podman_graphroot: /appl/containers/aap/storage
aap_deploy_manage_host_prep: true
aap_deploy_manage_rhsm_repos: false
ansible_remote_tmp: /appl/ansible-tmp
```

Large bundle copy and temporary space:
- Ansible copies modules and transfer payloads through `ansible_remote_tmp`.
  That is general Ansible runtime behavior, not AAP installer behavior.
- If the SSH user's home filesystem is small, set a larger remote temp path in
  inventory, for example:

```yaml
ansible_remote_tmp: /appl/ansible-tmp
```

Prepare custom `ansible_remote_tmp` paths before fact gathering or application
roles with `lit.foundational.ansible_remote_tmp`. It uses a raw bootstrap
command first because normal Ansible modules cannot run when `ansible_remote_tmp`
is missing or too restrictive.

## Installer Temporary Directory

For bundled/offline AAP installs, the vendor installer extracts and loads large
container images. If `/tmp` is small, the install can fail with:

```text
No space left on device
```

Use inventory to move both Ansible module staging and the installer process
temporary directory:

```yaml
ansible_remote_tmp: /appl/ansible-tmp
aap_deploy_manage_install_tmp_dir: true
aap_deploy_install_tmp_dir: /appl/tmp
aap_deploy_install_environment:
  TMPDIR: /appl/tmp
  TEMP: /appl/tmp
  TMP: /appl/tmp
```

`ansible_remote_tmp` controls Ansible module staging and should be prepared by
`lit.foundational.ansible_remote_tmp`. `aap_deploy_install_environment`
controls the environment of the AAP containerized installer task.
When `aap_deploy_manage_install_tmp_dir=true`, `aap_deploy_install_tmp_dir` is
created as `root:root` with mode `1777` so become-user workflows can use it.

Enable the temporary environment diagnostic when validating a new host:

```yaml
aap_deploy_debug_install_environment: true
```

Expected diagnostic output:

```text
TMPDIR=/appl/tmp
TEMP=/appl/tmp
TMP=/appl/tmp
tempfile.gettempdir()=/appl/tmp
```

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
  role.
- Preferred enterprise flow: use `lit.supplementary.aap_prepare` before
  `aap_cac` to download/copy/check the protected manifest onto the managed host.
- Inventory may still provide base64 content through
  `aap_cac_controller_license_manifest_content`.
- Do not commit real `manifest.zip` or `manifest.zip.b64` files.

Example:

```yaml
aap_cac_controller_license_manifest_content: >-
  {{ lookup('ansible.builtin.file', playbook_dir ~ '/files/aap/manifest.zip.b64') }}
```

Troubleshooting:
- `You must have a host set in the [automationmetrics] section`: this should
  not happen in the 2.7-only role. Verify the updated collection is active and
  the generated installer inventory contains `[automationmetrics]`.
- `automationmetrics_pg_host must be set and not empty`: verify the updated
  collection is active and the generated installer inventory contains
  `automationmetrics_pg_host` under `[all:vars]`. Override
  `aap_deploy_automationmetrics_pg_host` if using a custom database layout.
- `No space left on device` during bundle copy: set `ansible_remote_tmp` to a
  filesystem with enough free space and verify `aap_deploy_install_dir`.
- `gzip: /tmp/ansible... No space left on device`: the installer did not
  receive the custom temp environment or `/tmp` is too small. Check that the
  installer task has `environment: "{{ aap_deploy_installer_environment }}"`,
  and enable `aap_deploy_debug_install_environment` to confirm
  `tempfile.gettempdir()=/appl/tmp`.
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
- name: Install AAP 2.7 (growth, disconnected bundle)
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
        aap_deploy_setup_download_version: "2.7"
        aap_deploy_setup_download_containerized: true
        aap_deploy_bundle_dir: bundle

        # Customer baseline/Satellite example
        aap_deploy_manage_host_prep: true
        aap_deploy_manage_rhsm_repos: false

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

MIT

## Author

Lightning IT
