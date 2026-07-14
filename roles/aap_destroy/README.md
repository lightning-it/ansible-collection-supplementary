# aap_destroy

Execute vendor AAP removal role `infra.aap_utilities.aap_remove`.

## Requirements

Install the authoritative `collections/requirements-rh.yml` overlay; this
role's vendor teardown path requires its pinned `infra.aap_utilities` entry.

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
