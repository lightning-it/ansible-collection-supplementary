# aap_cac

AAP configuration-as-code role tasksets for AAP object configuration.

## Requirements

Install collections from:
- `collections/requirements.yml`

## Variables

See `roles/aap_cac/defaults/main.yml`.

Key variables:
- `aap_cac_collections_requirements`
- `aap_cac_gateway_hostname`
- `aap_cac_object_reconcile_orgs`
- `aap_cac_object_reconcile_secure_logging`
- `aap_cac_object_reconcile_protect_not_empty_orgs`

## Dependencies

None.

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

## License

GPL-3.0-only

## Author

Lightning IT
