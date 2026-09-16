# lit.supplementary.forward_proxy

Runs the distribution-neutral LIT Squid forward proxy as a digest-pinned Podman
container. Platform collections retain OS preparation, firewall, and client
configuration; this role never installs an OS Squid package.

## Requirements and security boundary

Requires rootful Podman/Quadlet, systemd, a preloaded immutable image, explicit
allowlists, trusted parent identities, and the experimental runtime opt-in. The
container runs as UID/GID 13 without capabilities or privilege escalation and
with a read-only root filesystem. The host firewall remains authoritative.

MIT — Lightning IT
