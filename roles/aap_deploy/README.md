# aap_deploy

Install AAP deployment package(s) for supported RHEL 9/10 hosts.

## Requirements

None.

## Variables

See `roles/aap_deploy/defaults/main.yml`.

Key variables:
- `aap_deploy_enabled`
- `aap_deploy_packages_rhel9`
- `aap_deploy_packages_rhel10`
- `aap_deploy_package_state`

Derived variables:
- `aap_deploy_target_major`
- `aap_deploy_packages_effective`

## Dependencies

None.

## Example Playbook

```yaml
- name: Deploy AAP packages
  hosts: aap_nodes
  gather_facts: true
  roles:
    - role: lit.supplementary.aap_deploy
      vars:
        aap_deploy_package_state: present
```

## License

GPL-3.0-only

## Author

Lightning IT
