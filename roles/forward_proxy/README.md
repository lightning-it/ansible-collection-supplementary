# lit.supplementary.forward_proxy

Runs the distribution-neutral LIT Squid forward proxy as a digest-pinned Podman
container. Platform collections retain OS preparation, firewall, and client
configuration; this role never installs an OS Squid package.

## Requirements and security boundary

Requires rootful Podman/Quadlet, systemd, a preloaded immutable image, explicit
allowlists, trusted parent identities, and the experimental runtime opt-in. The
container runs as UID/GID 13 without capabilities or privilege escalation and
with a read-only root filesystem. The host firewall remains authoritative.

## Example

```yaml
- name: Run the LIT forward proxy
  hosts: edge
  become: true
  roles:
    - role: lit.supplementary.forward_proxy
      forward_proxy_enabled: true
      forward_proxy_experimental_runtime_acceptance: true
      forward_proxy_allowed_destination_domains: [.ubuntu.com, .quay.io]
```

Variables: `defaults/main.yml`. Dependency: `lit.foundational.podman_systemd`.
`forward-proxy-tiny` verifies render, idempotence, cleanup, and redacted JUnit
evidence; live traffic acceptance remains a controlled Wunderbox operation.

MIT — Lightning IT
