# vault

Configure HashiCorp Vault.

## Requirements

None.

## Role Variables

See `defaults/main.yml`.

## Dependencies

This role uses the `terragrunt` role to configure Vault via Terraform.

## Example Playbook
```yaml
- name: Setup Vault
  hosts: localhost
  gather_facts: false
  roles:
    - role: vault
  tags:
    - vault
```

## Usage

### Prerequisites
Create an Ansible Vault password variable file and store it in
`host_vars/<YOUR VAULT SERVER>/ansible_vault_pw.yml`:
```bash
ansible-vault encrypt_string --name vault_ansible_vault_pw 'REPLACE_ME'
```

Create `host_vars/<YOUR VAULT SERVER>/02_vault.yml`:
```yaml
---
vault_host_ip: 10.10.52.100
vault_vault_hostname: vault01.degert-it.de
g_vault_addr: "https://{{ vault_vault_hostname }}:8200"
vault_url: "{{ g_vault_addr }}"
vault_terraform_source: "git::ssh://gitea@dms.degert-it.de:2022/terraform/hashicorp_vault.git?ref=main"
vault_secret_stores:
  - path: stage-2c
    description: "stage-2c Secrets"
  - path: pki-secrets
    description: "PKI Secrets"
```

### Deploy Vault
```bash
ansible-navigator run playbooks/common/01_hashicorp_vault.yml -i inventory/ --m stdout -b --ask-vault-password -e vault_vault_validate_certs=false -e vault_hashi_vault_auth_method=token
```

### Unseal Vault
```bash
ansible-navigator run playbooks/common/01_hashicorp_vault.yml -i inventory/ --m stdout -b --ask-vault-password -e vault_vault_validate_certs=false -e vault_hashi_vault_auth_method=token -t unseal
```

### Get Vault root token (login)
The root token is stored in the encrypted `vault-init.yml` file.
This command will prompt for the Ansible Vault password:
```bash
ansible localhost -m debug -a "var=vault_unseal_keys_encrypted" \
  -e @host_vars/<YOUR VAULT SERVER>/vault-init.yml \
  --vault-password-file "$(pwd)/.vault-pass.txt"

```
Copy the `root_token` value from the JSON and use it to log in:
```bash
vault login <root_token>
```

## License

BSD

## Author Information

Dirk Egert
