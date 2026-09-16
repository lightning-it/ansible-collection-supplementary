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

The role requires an immutable image, explicit client and destination
allowlists, trusted parent identities, and a bounded per-host transaction lock.
Runtime activation additionally requires the temporary experimental acceptance
flag. Image preload and host firewall approval are separate controlled steps.

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
      forward_proxy_experimental_runtime_acceptance: true
      forward_proxy_allowed_destination_domains:
        - .ubuntu.com
        - .quay.io
        - .redhat.com
```

The runtime example assumes the pinned image was preloaded and the matching
host firewall owner rule was approved. The temporary explicit acceptance opt-in
remains required until protected Wunderbox live acceptance is recorded.
Activation and firewall cutover remain controlled operational steps.

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
