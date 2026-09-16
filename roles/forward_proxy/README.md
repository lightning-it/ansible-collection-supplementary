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
- `forward_proxy_experimental_runtime_acceptance`: explicit opt-in used only for
  the controlled Wunderbox runtime acceptance until protected live Podman,
  systemd, listener, rollback, allowed-proxy, and denied-direct evidence exists.
- `forward_proxy_lock_path` and `forward_proxy_lock_timeout`: bounded per-host
  mutual exclusion for the complete inspect, transition, runtime, rollback,
  disable, and marker-commit transaction. Stale locks require operator review.
- `forward_proxy_render_root`: exact containment root for non-root render-only output.
- `forward_proxy_trusted_parent_paths`: complete parent chains, rooted at
  existing canonical anchors and ordered parent before child. Every component
  is revalidated as a non-symlink before a write or rollback.
- `forward_proxy_image`: immutable digest-pinned image defined by the role defaults.
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
- name: Render the LIT forward proxy service definition
  hosts: edge
  become: true
  roles:
    - role: lit.supplementary.forward_proxy
      forward_proxy_enabled: true
      forward_proxy_manage_runtime: false
      forward_proxy_allowed_destination_domains:
        - .ubuntu.com
        - .quay.io
        - .redhat.com
```

The render-only example assumes the pinned image was preloaded and the matching
host firewall owner rule was approved. It does not create a Quadlet or start
systemd. Runtime activation additionally requires
`forward_proxy_manage_runtime: true` and the temporary explicit
`forward_proxy_experimental_runtime_acceptance: true` opt-in until protected
Wunderbox live acceptance is recorded. Activation and firewall cutover remain
controlled operational steps.

## License

MIT

## Author

Lightning IT

## Verification status

`forward-proxy-tiny` provides local render, policy, cleanup, JUnit, and
redacted-evidence checks. While the role remains experimental, this scenario
is manual pre-merge evidence and is deliberately not represented as a protected
CI matrix cell. Protected live Podman, firewall, allowed-proxy, and denied-direct
traffic acceptance follows on the Wunderbox target before production maturity.
