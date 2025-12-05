# keycloak_platform_terraform

An Ansible role that drives the `terraform-keycloak-platform` module to manage
Keycloak realms. Ansible provides the data (realms, connection details), and
Terraform applies the configuration via the Keycloak provider.

This role is intended to live in the **`ansible-collection-supplementary`**
collection as an optional infrastructure service.

---

## What it does

- Ensures a Terraform working directory exists on the control host
- Renders a `main.tf` that:
  - configures the `keycloak` provider
  - calls the Terraform module:
    - `app.terraform.io/l-it/platform/keycloak`
- Runs `terraform init`
- Runs `terraform apply` to create/update Keycloak realms

Terraform itself must be installed and available in `PATH` on the control host.

---

## Role variables

Defined in `defaults/main.yml`:

```yaml
# Terraform working directory on the control host
keycloak_tf_workdir: "/srv/infra/keycloak"

# List of realms to manage (MUST be overridden)
keycloak_realms: []

# Keycloak provider settings (MUST be overridden)
keycloak_url: null
keycloak_client_id: null
keycloak_client_secret: null
keycloak_master_realm: null

# Terraform module source and version (can be overridden)
keycloak_module_source: "app.terraform.io/l-it/platform/keycloak"
keycloak_module_version: "1.0.0"
