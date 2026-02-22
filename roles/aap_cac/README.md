# aap_cac

AAP configuration-as-code role tasksets for AAP object configuration.

## Requirements

Install `lit.supplementary` via `ansible-galaxy collection install` so
dependencies from `galaxy.yml` are installed automatically.

Optional overlay file (for additional non-matrix dependencies):
- `collections/requirements.yml`

Default used by this role:
- `aap_cac_collections_requirements` -> `collections/requirements.yml`

## Variables

See `roles/aap_cac/defaults/main.yml`.

Key variables:
- `aap_cac_collections_requirements`
- `aap_cac_required_collection_matrix`
- `aap_cac_gateway_hostname`
- `aap_cac_token_description`
- `aap_cac_object_reconcile_orgs`
- `aap_cac_object_reconcile_secure_logging`
- `aap_cac_object_reconcile_protect_not_empty_orgs`
- `aap_cac_enable_aap_utilities_roles`
- `aap_cac_aap_utilities_roles`
- `aap_cac_enable_controller_configuration_roles`
- `aap_cac_controller_configuration_roles`
- `aap_cac_enable_ee_utilities_roles`
- `aap_cac_ee_utilities_roles`

## Dependencies

This role validates and expects the AAP CaC collection matrix defined in
`roles/aap_cac/defaults/main.yml` (`aap_cac_required_collection_matrix`).

The required matrix is enforced against collection metadata in `galaxy.yml`.
`collections/requirements.yml` is an optional overlay for additional
non-matrix dependencies.

## Example Playbook

```yaml
- name: Apply AAP configuration-as-code
  hosts: aaps
  become: true
  gather_facts: true
  roles:
    - role: lit.supplementary.aap_cac
      vars:
        aap_cac_gateway_hostname: "https://{{ inventory_hostname }}"
```

Run a single taskset directly:

```yaml
- name: Apply only gateway organizations
  hosts: aaps
  become: true
  gather_facts: true
  tasks:
    - name: Include aap_cac taskset
      ansible.builtin.include_role:
        name: lit.supplementary.aap_cac
        tasks_from: cac_11_gateway_organizations.yml
```

Hub sync is covered by running:
- `cac_30_hub_collection_remotes.yml`
- `cac_31_hub_collection_repositories.yml`
- `cac_32_hub_collection_repository_sync.yml`

Optional role-dispatch tasksets:
- `cac_34_aap_utilities_roles.yml`
- `cac_35_controller_configuration_roles.yml`
- `cac_36_ee_utilities_roles.yml`

## License

GPL-3.0-only

## Author

Lightning IT
