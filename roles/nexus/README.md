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
ansible-navigator run playbooks/common/02_nexus.yml -i inventory/ --m stdout \
  -e nexus_vault_auth_method=token -e nexus_vault_validate_certs=false \
  -e vault_token="$(cat $HOME/.vault-token)"
```

If you use AppRole, ensure Vault KV contains the credentials at:

```
<engine_mount>/<inventory_hostname>/nexus/approle-kv
<engine_mount>/<inventory_hostname>/nexus/approle-pki
```

and run with a `vault_token` that can read those paths.

#### Deploy users (only initial Password can be set)
```bash
ansible-navigator run playbooks/common/02_nexus.yml -i inventory/ --m stdout \
  -e nexus_vault_auth_method=token -e nexus_vault_validate_certs=false -t users \
  -e vault_token="$(cat $HOME/.vault-token)"
```
