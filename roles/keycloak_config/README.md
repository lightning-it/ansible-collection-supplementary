# keycloak_platform_terraform

An Ansible role that drives the `terraform-keycloak-instance` module to manage a
Keycloak instance. Ansible supplies the data (realms, clients, roles, groups,
IdPs, policies), and Terraform applies it through the official Keycloak
provider.

Terraform must be installed and available in `PATH` on the control host.

---

## What it does

- Prepares a Terraform working directory on the control host.
- Renders a `main.tf` that configures the Keycloak provider and calls
  `lightning-it/instance/keycloak` (or an override).
- Runs `terraform init` and `terraform apply` to create/update Keycloak realms
  and related objects.

---

## Role variables

| Variable | Type / Default | Description |
| --- | --- | --- |
| `keycloak_tf_workdir` | string, default `/workspace/infra/keycloak` | Directory on the control host where Terraform runs. |
| `keycloak_tf_clean_state` | bool, default `false` | Remove `.terraform` and state files before each run. |
| `keycloak_realms` | list(object), default `[]` | Realms to manage (name, display_name, etc.). **Must be set.** |
| `keycloak_module_source` | string, default `lightning-it/instance/keycloak` | Terraform module source. |
| `keycloak_module_version` | string, default `1.2.1` | Terraform module version (set `null` for local path). |
| `keycloak_url` | string, default `""` | Keycloak base URL. |
| `keycloak_client_id` | string, default `""` | Client ID for auth. |
| `keycloak_client_secret` | string, default `""` | Client secret (when using client credentials). |
| `keycloak_username` | string, default `""` | Username for admin/password auth. |
| `keycloak_password` | string, default `""` | Password for admin/password auth. |
| `keycloak_master_realm` | string, default `""` | Realm used for authentication (usually `master`). |
| `keycloak_clients` | list(object), default `[]` | Clients to pass to the Terraform module. |
| `keycloak_client_scopes` | list(object), default `[]` | Client scopes to pass through. |
| `keycloak_realm_roles` | list(object), default `[]` | Realm roles to configure. |
| `keycloak_client_roles` | list(object), default `[]` | Client roles to configure. |
| `keycloak_role_bindings` | list(object), default `[]` | Role bindings for users/groups/service accounts. |
| `keycloak_groups` | list(object), default `[]` | Groups to configure. |
| `keycloak_default_groups` | list(object), default `[]` | Default groups per realm. |
| `keycloak_users` | list(object), default `[]` | Users to seed. |
| `keycloak_service_accounts` | list(object), default `[]` | Service accounts per client. |
| `keycloak_identity_providers` | list(object), default `[]` | OIDC/SAML IdPs. |
| `keycloak_identity_provider_mappers` | list(object), default `[]` | IdP mappers. |
| `keycloak_ldap_user_federations` | list(object), default `[]` | LDAP federation configs. |
| `keycloak_kerberos_user_federations` | list(object), default `[]` | Kerberos federation configs. |
| `keycloak_theme_settings` | list(object), default `[]` | Theme selection per realm. |
| `keycloak_localization_settings` | list(object), default `[]` | Localization settings per realm. |
| `keycloak_custom_theme_hooks` | list(object), default `[]` | Metadata for custom themes. |
| `keycloak_smtp_settings` | list(object), default `[]` | SMTP settings per realm. |
| `keycloak_password_policies` | list(object), default `[]` | Password policy strings per realm. |
| `keycloak_bruteforce_settings` | list(object), default `[]` | Brute-force protection settings. |
| `keycloak_auth_flow_settings` | list(object), default `[]` | Login/auth flow toggles. |
| `keycloak_otp_settings` | list(object), default `[]` | OTP/MFA settings. |
| `keycloak_event_settings` | list(object), default `[]` | Event listener and admin event settings. |
| `keycloak_event_listener_hooks` | list(object), default `[]` | Metadata for custom event listeners. |
| `keycloak_session_settings` | list(object), default `[]` | Session timeout settings. |
| `keycloak_token_settings` | list(object), default `[]` | Token lifetime settings. |

All lists above are passed directly to the underlying Terraform module; see the
module documentation for exact shapes.

---

## Usage

Example playbook:

```yaml
- hosts: keycloak
  gather_facts: false
  vars:
    keycloak_tf_workdir: "/tmp/keycloak-tf"
    keycloak_url: "http://localhost:8080"
    keycloak_master_realm: "master"
    keycloak_client_id: "admin-cli"
    keycloak_username: "admin"
    keycloak_password: "admin"
    keycloak_realms:
      - name: "demo01"
        display_name: "DEMO01"
    keycloak_clients:
      - client_id: "app-frontend"
        realm: "demo01"
        client_type: "public"
        redirect_uris: ["http://localhost:3000/*"]
  roles:
    - role: lightning_it.supplementary.keycloak
```

This renders a Terraform configuration that calls
`lightning-it/instance/keycloak` with the provided inputs, then runs
`terraform init` and `terraform apply`.

---

## Idempotence

The role is expected to be idempotent: running it a second time with the same
inputs should report no changes (Terraform will print `No changes.`). Terraform
init and clean-up steps are marked as not changing state.

---

## Tested ansible-core versions

- 2.14.18 (RHEL 9 AppStream)
- 2.16.11 (AAP stable EE)
- 2.18.6 (AAP latest EE)
