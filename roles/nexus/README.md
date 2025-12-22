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
