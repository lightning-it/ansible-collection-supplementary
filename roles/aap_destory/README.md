# aap_destory

Deprecated compatibility wrapper for the misspelled role name.

Use `lit.supplementary.aap_destroy` for new playbooks. This role delegates to
`aap_destroy` so older playbooks keep working during migration.

## Requirements

`infra.aap_utilities` collection installed.

## Variables

See `roles/aap_destroy/defaults/main.yml`.

Key variables:
- `aap_destroy_enabled`
- `aap_destory_enabled` for compatibility with existing playbooks

## Dependencies

None.

## Example Playbook

```yaml
- name: Remove AAP
  hosts: aap_nodes
  gather_facts: true
  roles:
    - role: lit.supplementary.aap_destory
      vars:
        aap_destory_enabled: true
```

## License

MIT

## Author

Lightning IT
