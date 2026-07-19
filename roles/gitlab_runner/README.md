# GitLab Runner Role

This role is deprecated. It never acquired an operational GitLab Runner
implementation and now fails closed on every invocation. It must not be used as
deployment or test coverage.

## Requirements

A maintained runner deployment path. Re-enabling this role requires a real
implementation plus Tiny, Heavy, and Application Acceptance scenarios that
register a runner and execute a harmless workload.

## Variables

See `defaults/main.yml`.

## Dependencies

The role has no runtime dependencies because it does not deploy anything.

## Example Playbook

```yaml
---
- name: Use lit.supplementary.gitlab_runner
  hosts: all
  become: true
  roles:
    # Do not invoke: the deprecated role fails closed.
    - role: lit.supplementary.gitlab_runner
```

## License

MIT

## Author

Lightning IT

## Additional Notes

### Usage Documentation

See the collection coverage registry for the `deprecated` disposition.

### Testing

The legacy scenario proves only that the deprecation guard rejects invocation;
it is not deployment coverage:

```bash
molecule test -s gitlab-runner-basic
```
