# aap_cac

AAP configuration-as-code role tasksets for AAP object configuration.

## Requirements

Ensure `lit.supplementary` and its dependencies are preinstalled by your
workspace/EE preparation flow.
Collection installation and packaging are out of scope for role task execution.

## Variables

See `roles/aap_cac/defaults/main.yml`.

Key variables:
- `aap_cac_gateway_hostname`
- `aap_cac_gateway_username` (default: `admin`)
- `aap_cac_gateway_password` (default: `aap_gateway_admin_password_effective`)
- `aap_cac_gateway_validate_certs` (defaults to `aap_validate_certs`)
- `aap_cac_token_description`
- `aap_cac_token_request_retries`
- `aap_cac_token_request_delay`
- `aap_cac_gateway_ready_check`
- `aap_cac_gateway_ready_path`
- `aap_cac_gateway_ready_status_codes`
- `aap_cac_gateway_ready_retries`
- `aap_cac_gateway_ready_delay`
- `aap_cac_enable_controller_license`
- `aap_cac_controller_license_state`
- `aap_cac_controller_license_force`
- `aap_cac_controller_license_secure_logging`
- `aap_cac_controller_license_manifest_content`
- `aap_cac_object_reconcile_orgs`
- `aap_cac_object_reconcile_secure_logging`
- `aap_cac_object_reconcile_protect_not_empty_orgs`
- `aap_cac_enable_aap_utilities_roles`
- `aap_cac_aap_utilities_roles`
- `aap_cac_enable_controller_configuration_roles`
- `aap_cac_controller_configuration_roles`
- `aap_cac_enable_ee_utilities_roles`
- `aap_cac_ee_utilities_roles`

Password and secret input behavior:
- Inventory is the source of truth.
- Inventory may provide plain values, Ansible Vault values, or lookup-based values (for example HCP Vault).
- This role does not read or write Vault directly.

## Dependencies

Collection dependencies are declared at collection level in `galaxy.yml`
and must be provisioned by your EE/workspace install flow before role execution.

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

Controller license activation via manifest content from inventory:

```yaml
- name: Apply AAP configuration-as-code
  hosts: aaps
  become: true
  gather_facts: true
  roles:
    - role: lit.supplementary.aap_cac
      vars:
        aap_cac_enable_controller_license: true
        aap_cac_controller_license_manifest_content: "{{ vault_aap_subscription_manifest_b64 }}"
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

Optional additional tasksets:
- `cac_19_controller_license.yml` (manifest content only)

Optional role-dispatch tasksets:
- `cac_34_aap_utilities_roles.yml`
- `cac_35_controller_configuration_roles.yml`
- `cac_36_ee_utilities_roles.yml`

## License

GPL-3.0-only

## Author

Lightning IT
