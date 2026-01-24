# Nexus Role

Provision Sonatype Nexus Repository Manager as part of the
`lit.foundation_services` collection. The role is currently a template
and documents the intended interface for future development.

## Usage Documentation

Consult the collection `README.md` for configuration variables, storage
settings, and operational guidelines shared across all foundation services.

## Testing

Run the bundled Molecule scenario prior to publishing updates:

```bash
molecule test -s default
```

### Prerequisites
#### VAULT login
```bash
VAULT_ADDR=https://vault01.example.com:8200 vault login
```
#### Deploy Nexus
```bash
VAULT_TOKEN=$(cat $HOME/.vault-token) ansible-navigator run playbooks/common/02_nexus.yml -i inventory/ --m stdout -e nexus_vault_auth_method=token -e nexus_vault_validate_certs=false
```

If you use AppRole, supply the role credentials (or set `nexus_vault_role_name`
to pick from `vault_approle_credentials` when the Vault role runs earlier):

```bash
ansible-navigator run playbooks/common/02_nexus.yml -i inventory/ --m stdout \
  -e nexus_vault_auth_method=approle \
  -e nexus_vault_role_id=ROLE_ID \
  -e nexus_vault_secret_id=SECRET_ID
```

#### Deploy users (only initial Password can be set)
```bash
VAULT_TOKEN=$(cat $HOME/.vault-token) ansible-navigator run playbooks/common/02_nexus.yml -i inventory/ --m stdout -e nexus_vault_auth_method=token -e nexus_vault_validate_certs=false -t users
```
