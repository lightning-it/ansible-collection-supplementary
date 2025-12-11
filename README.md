# lightning_it.supplementary

Supplementary Ansible collection for ModuLix / Lightning IT. Currently contains
the `keycloak_config` role to configure existing Keycloak instances (realms,
clients, roles, users, IdPs) via Terraform.

## Usage

Install directly from the repo/branch:

```bash
ansible-galaxy collection install \
  git+https://github.com/lightning-it/ansible-collection-supplementary.git,ro/role-keycloak
```

Example playbook:

```yaml
- hosts: keycloak
  gather_facts: false
  connection: local

  roles:
    - role: lightning_it.supplementary.keycloak_config
```

## Development

- `galaxy.yml` defines the collection metadata (namespace `lightning_it`, name
  `supplementary`, license `GPL-2.0-only`).
- Source tree includes a convenience mirror under
  `ansible_collections/lightning_it/supplementary/` for local execution; the
  canonical role sources live in `roles/`.
- Molecule scenario `keycloak-local` provisions a local Keycloak container and
  exercises the role with `keycloak_config_skip_apply` set for quick checks.
