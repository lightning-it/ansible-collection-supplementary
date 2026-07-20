# lit.supplementary.manage_esxi

## Requirements

None.

## Variables

See `defaults/main.yml`.

## Dependencies

None.

## Example Playbook

```yaml
---
- name: Use lit.supplementary.manage_esxi
  hosts: all
  become: true
  roles:
    - role: lit.supplementary.manage_esxi
```

## License

MIT

## Author

Lightning IT
