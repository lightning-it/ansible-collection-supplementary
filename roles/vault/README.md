# vault

Role to configure Hashicorp Vault
 
## Requirements

No.

## Role Variables

See defaults/main.yml

## Dependencies

This role uses the role terragrunt to configure vault via terraform.

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
## Usage

### Prerequisites
Create new ansible-vault password and encrypt this password. Put it into host_vars/<YOUR VAULT SERVER>/ansible_vault_pw.yml
```bash
ansible-vault encrypt_string
```
Create host_vars/<YOUR VAULT SERVER>/02_vault.yml
```yaml
---
vau_host_ip: 10.10.52.100
vau_vault_hostname: vault01.degert-it.de
g_vault_addr: "https://{{ vau_vault_hostname }}:8200"
vau_url: "{{ g_vault_addr }}"
vau_terraform_source: "git::ssh://gitea@dms.degert-it.de:2022/terraform/hashicorp_vault.git?ref=main"
vau_secret_stores:
  - path: stage-2c
    description: "stage-2c Secrets"
  - path: pki-secrets
    description: "PKI Secrets"
```

### Deploy vault
```bash
ansible-navigator run playbooks/common/01_hashicorp_vault.yml -i inventory/ --m stdout -b --ask-vault-password -e vau_vault_validate_certs=false -e vau_hashi_vault_auth_method=token
```

### Unseal vault
```bash
ansible-navigator run playbooks/common/01_hashicorp_vault.yml -i inventory/ --m stdout -b --ask-vault-password -e vau_vault_validate_certs=false -e vau_hashi_vault_auth_method=token -t unseal
```

## License

BSD

## Author Information

Dirk Egert
