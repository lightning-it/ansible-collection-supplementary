# aap_destory

Execute vendor AAP removal role `infra.aap_utilities.aap_remove`.

## Requirements

`infra.aap_utilities` collection installed.

## Variables

See `roles/aap_destory/defaults/main.yml`.

Key variables:
- `aap_destory_enabled`

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

GPL-3.0-only

## Author

Lightning IT
