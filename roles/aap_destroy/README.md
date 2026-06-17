# aap_destroy

Execute vendor AAP removal role `infra.aap_utilities.aap_remove`.

## Requirements

`infra.aap_utilities` collection installed.

## Variables

See `roles/aap_destroy/defaults/main.yml`.

Key variables:
- `aap_destroy_enabled`

## Dependencies

None.

## Example Playbook

```yaml
- name: Remove AAP
  hosts: aap_nodes
  gather_facts: true
  roles:
    - role: lit.supplementary.aap_destroy
      vars:
        aap_destroy_enabled: true
```

## License

MIT

## Author

Lightning IT
