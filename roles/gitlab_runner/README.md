# GitLab Runner Role

This role installs and configures GitLab Runner as part of the
`lit.foundation_services` collection. It currently provides a skeleton
implementation and is meant to be extended with platform-specific logic.

## Requirements

None.

## Variables

See `defaults/main.yml`.

## Dependencies

None.

## Example Playbook

```yaml
---
- name: Use lit.supplementary.gitlab_runner
  hosts: all
  become: true
  roles:
    - role: lit.supplementary.gitlab_runner
```

## License

MIT

## Author

Lightning IT

## Additional Notes

### Usage Documentation

Refer to the collection-level `README.md` for supported variables, expected
inventory configuration, and integration details.

### Testing

Execute Molecule before publishing changes:

```bash
molecule test -s default
```
