# lit.supplementary.forward_proxy

Runs the standard LIT Squid forward proxy as a persistent, digest-pinned
Podman container on prepared Ubuntu or Enterprise Linux hosts. It permits only
explicitly configured destination domains and can chain all traffic to one
customer or site upstream proxy.

This role owns the distribution-neutral proxy service. Operating-system client
configuration belongs to adapters such as `lit.ubuntu.forward_proxy_client`.
The role never installs an operating-system Squid package.

## Requirements

Rootful Podman with Quadlet support, systemd, and root privileges. The exact
Squid image must already be present locally before runtime management is
enabled. Host preparation and outbound firewall policy belong to the applicable
operating-system collection.

The collection uses `lit.foundational.podman_systemd` for persistent lifecycle
management.

## Variables

See `roles/forward_proxy/defaults/main.yml`.

Important inputs include:

- `forward_proxy_enabled`: enable or safely remove the role-owned service.
- `forward_proxy_manage_runtime`: manage Quadlet/systemd or only render test fixtures.
- `forward_proxy_render_root`: exact containment root for non-root render-only output.
- `forward_proxy_image`: immutable `docker.io/ubuntu/squid:6.6-24.04_beta@sha256:...` image.
- `forward_proxy_image_pull_policy`: fixed to `Never`; image preload is a separate bootstrap step.
- `forward_proxy_listen_addresses` and `forward_proxy_allowed_clients`: exact ingress boundary.
- `forward_proxy_allowed_destination_domains`: mandatory closed destination allowlist when enabled.
- `forward_proxy_upstream_*`: optional unauthenticated customer/site parent proxy.

The container uses host networking and runs as UID/GID 13 from the pinned
image. It drops every capability, prohibits privilege escalation, and uses a
read-only root filesystem with ephemeral `/tmp`. Proxy environment variables
are routing configuration, not a security boundary; the host firewall remains
authoritative.

Authenticated upstream proxies remain unsupported until a secret-backed
interface exists. Credentials must not be placed in inventory.

## Dependencies

- `lit.foundational.podman_systemd`
- a distribution-specific host preparation and firewall role
- optionally a distribution-specific client adapter

## Example Playbook

```yaml
- name: Run the LIT forward proxy service
  hosts: edge
  become: true
  roles:
    - role: lit.supplementary.forward_proxy
      forward_proxy_enabled: true
      forward_proxy_allowed_destination_domains:
        - .ubuntu.com
        - .quay.io
        - .redhat.com
```

The example assumes the pinned image was preloaded and the matching host
firewall owner rule was approved. Activation and firewall cutover remain
controlled operational steps.

## License

MIT

## Author

Lightning IT
