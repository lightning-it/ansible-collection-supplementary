# GitLab Runner Role

This role installs and configures GitLab Runner as part of the
`lit.foundation_services` collection. It currently provides a skeleton
implementation and is meant to be extended with platform-specific logic.

## Usage Documentation

Refer to the collection-level `README.md` for supported variables, expected
inventory configuration, and integration details.

## Testing

Execute Molecule before publishing changes:

```bash
molecule test -s default
```

