# keycloak_config role

Configure an existing Keycloak instance (realms, clients, roles, users, IdPs,
policies) via Terraform. Ansible supplies the data; Terraform applies it through
the official Keycloak provider.

Terraform must be installed and available in `PATH` on the control host.

---

## What it does

- Prepares a Terraform working directory on the control host.
- Renders a `main.tf` that configures the Keycloak provider and calls
  `lightning-it/instance/keycloak` (or an override).
- Runs `terraform init` and optionally `terraform apply` to create/update
  Keycloak realms and related objects.

---

## Role variables

Key inputs (all prefixed with `keycloak_config_`):

- `keycloak_config_tf_workdir` (string, default `/workspace/infra/keycloak`):
  directory on the control host where Terraform runs.
- `keycloak_config_tf_clean_state` (bool, default `false`):
  remove `.terraform` and state files before each run.
- `keycloak_config_skip_apply` (bool, default `false`):
  skip `terraform apply` (render only).
- `keycloak_config_url` (string): Keycloak base URL. **Required**
- `keycloak_config_master_realm` (string): realm used for authentication.
- `keycloak_config_client_id` (string): client ID for auth.
- `keycloak_config_client_secret` (string): client secret when using client
  credentials.
- `keycloak_config_username` / `keycloak_config_password` (strings):
  admin username/password alternative auth.
- `keycloak_config_realms` (list): realms to manage. **Required**
- `keycloak_config_module_source` (string, default `lightning-it/instance/keycloak`)
  and `keycloak_config_module_version` (string, default `1.2.1`): Terraform
  module source/version (set version to `null` for a local path).

Other optional lists passed through to the Terraform module:

- `keycloak_config_clients`
- `keycloak_config_client_scopes`
- `keycloak_config_realm_roles`
- `keycloak_config_client_roles`
- `keycloak_config_role_bindings`
- `keycloak_config_groups`
- `keycloak_config_default_groups`
- `keycloak_config_users`
- `keycloak_config_service_accounts`
- `keycloak_config_identity_providers`
- `keycloak_config_identity_provider_mappers`
- `keycloak_config_ldap_user_federations`
- `keycloak_config_kerberos_user_federations`
- `keycloak_config_theme_settings`
- `keycloak_config_localization_settings`
- `keycloak_config_custom_theme_hooks`
- `keycloak_config_smtp_settings`
- `keycloak_config_password_policies`
- `keycloak_config_bruteforce_settings`
- `keycloak_config_auth_flow_settings`
- `keycloak_config_otp_settings`
- `keycloak_config_event_settings`
- `keycloak_config_event_listener_hooks`
- `keycloak_config_session_settings`
- `keycloak_config_token_settings`

See the Terraform module documentation for the exact shapes.

---

## Usage

Example playbook using the collection FQCN:

```yaml
- hosts: keycloak
  gather_facts: false
  vars:
    keycloak_config_tf_workdir: "/tmp/keycloak-tf"
    keycloak_config_url: "http://localhost:8080"
    keycloak_config_master_realm: "master"
    keycloak_config_client_id: "admin-cli"
    keycloak_config_username: "admin"
    keycloak_config_password: "admin"
    keycloak_config_realms:
      - name: "demo01"
        display_name: "DEMO01"
    keycloak_config_clients:
      - client_id: "app-frontend"
        realm: "demo01"
        client_type: "public"
        redirect_uris: ["http://localhost:3000/*"]
  roles:
    - role: lit.supplementary.keycloak_config
```

---

## Idempotence

The role is expected to be idempotent: re-running with the same inputs should
report no changes (Terraform prints `No changes.`). Terraform init and clean-up
steps are marked as not changing state.

---

## Tested ansible-core versions

- 2.14.18 (RHEL 9 AppStream)
- 2.16.11 (AAP stable EE)
- 2.18.6 (AAP latest EE)
