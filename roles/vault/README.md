# Vault Role

Deploy HashiCorp Vault using the shared patterns defined in the
`lit.foundation_services` collection. This role is a scaffold awaiting
full implementation but already defines the variables and testing hooks.

## Usage Documentation

All public variables and orchestration guidance live in the collection
`README.md`. Update that file when introducing new role inputs.

## Testing

Execute Molecule to verify behavioural changes:

```bash
molecule test -s default
```
