# lit.supplementary.aap_deploy

Role for AAP deployment flows on RHEL 9/10.

## Requirements

None.

## Role Variables

- `aap_deploy_enabled` (bool, default: `true`): enable or disable the role.
- `aap_deploy_instance_name` (string, default: empty): label for logging.
- `aap_deploy_namespace` (string, default: empty): namespace label for logging.
- `aap_deploy_packages_rhel9` (list, default: `["aap-deploy"]`): packages to
  install on RHEL 9.
- `aap_deploy_packages_rhel10` (list, default: `["aap-deploy"]`): packages to
  install on RHEL 10.
- `aap_deploy_package_state` (string, default: `present`): package state.

## Example Playbook

```yaml
- hosts: localhost
  gather_facts: false
  roles:
    - role: lit.supplementary.aap_deploy
      vars:
        aap_deploy_instance_name: demo-aap
        aap_deploy_namespace: aap
```
