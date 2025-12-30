# vault

Role to configure Hashicorp Vault
 
## Requirements

No.

## Role Variables

See defaults/main.yml

## Dependencies

This role uses the role terragrunt to configure artifactory via terraform.

## Example Playbook
```
- name: "Setup Vault"
  hosts: localhost
  gather_facts: false
  roles:
    - role: vault
  tags:
    - vault
```

## License

BSD

## Author Information

Dirk Egert
