# forward_proxy

## Requirements

Rootful Podman, systemd, preloaded image, allowlists, trusted parents and opt-in.
UID/GID 13, no capabilities, read-only rootfs; host firewall authoritative.
The pinned Squid image supplies `/bin/bash`; the container liveness probe uses
its built-in `/dev/tcp` support for an HTTP request and requires no added tool.
Before any enabled-state mutation, the role executes that pinned image once
with no network, a read-only root filesystem, no capabilities and
`no-new-privileges`; the apply fails closed unless `/bin/bash` and its `printf`
builtin are available.

## Variables

`defaults/main.yml`.

## Dependencies

`lit.foundational` 1.32.0 or newer, specifically its `podman_systemd`
role. The authoritative collection constraint remains in `galaxy.yml`.

## Example Playbook

```yaml
- name: Run the digest-pinned forward proxy on prepared Podman hosts
  hosts: proxies
  become: true
  vars:
    # The image from defaults/main.yml must already exist on the host because
    # the enforced pull policy is Never.
    forward_proxy_enabled: true
    forward_proxy_experimental_runtime_acceptance: true
    forward_proxy_allowed_destination_domains:
      - .ubuntu.com
      - registry.example.com
  roles:
    - role: lit.supplementary.forward_proxy
```

The target must provide rootful Podman and systemd before this role runs. Keep
the experimental opt-in explicit until protected Wunderbox runtime acceptance
promotes the role's Tiny profile beyond `experimental`.

## License

MIT

## Author

Lightning IT
