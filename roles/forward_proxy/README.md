# forward_proxy

## Requirements

Rootful Podman, systemd, preloaded image, allowlists, trusted parents and opt-in.
UID/GID 13, no capabilities, read-only rootfs; host firewall authoritative.

## Variables

`defaults/main.yml`.

## Dependencies

`galaxy.yml`.

## Example Playbook

```yaml
- hosts: proxies
  roles: [lit.supplementary.forward_proxy]
```

## License

MIT

## Author

Lightning IT
