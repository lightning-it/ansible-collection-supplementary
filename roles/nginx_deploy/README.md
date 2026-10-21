# nginx_deploy

Deploy Nginx from a rendered Kubernetes YAML manifest. Persistent lifecycle is
owned exclusively by a native Quadlet `.kube` unit through
`lit.foundational.podman_systemd`; direct kubeplay is limited to an explicit
non-systemd mode.

## Requirements

None.

## Variables

See `roles/nginx_deploy/defaults/main.yml`.

Key variables:
- `nginx_deploy_image`
- `nginx_deploy_pod_manifest_path`
- `nginx_deploy_host_conf_dir`
- `nginx_deploy_host_root`
- `nginx_deploy_listen_port`
- `nginx_deploy_tls_listen_port`
- `nginx_deploy_port_bindings`
- `nginx_deploy_networks` (native Quadlet `Network=` entries)
- `nginx_deploy_manage_default_site`
- `nginx_deploy_manage_systemd`
- `nginx_deploy_systemd_unit_name`
- `nginx_deploy_systemd_scope` (`system`, or explicit experimental `user`)
- `nginx_deploy_quadlet_dir`
- `nginx_deploy_systemd_enabled` (must remain `true` for generated Quadlet services)
- `nginx_deploy_selinux_relabel`
- `nginx_deploy_skip_runtime`

Set `nginx_deploy_networks` to the private application network when NGINX is
the exclusive ingress and reaches backends through Podman DNS names. Persistent
start, stop, restart and removal remain owned by the native Quadlet unit.
The default native unit is `<pod-name>-pod.service`, avoiding collisions with
an administrator-managed `nginx.service`. Enabling systemd management without
a detected systemd service manager fails during prechecks.
Changes that would restart an already existing native Quadlet fail closed until
transactional manifest backup and restore support is available.
Managed-systemd mode rejects `nginx_deploy_systemd_enabled: false` because the
generated Quadlet unit cannot converge to a durable disabled state.

### Rootless user scope (experimental)

Set `nginx_deploy_systemd_scope: user` explicitly to use native User Quadlets.
The caller supplies Podman, the non-root application account and its home,
user-systemd startup without login, writable persistent directories, and any
privileged-port allowance. This mode does not install packages or prepare the OS.
It is a separate experimental path; existing system-scope platform and test
claims do not establish rootless production support.

Runtime credentials are supplied by the caller from encrypted inventory and
rendered as owner-only environment files required by Podman. They are not
controller-generated secrets and must not be logged or committed. Existing
PostgreSQL data must retain its matching database credentials. No database
migration, downgrade, or backup/restore is implied by a deployment rerun.

One application stack per account is currently supported: unit/container names
are `keycloak`, `postgres`, and `nginx`, with the `keycloak-private.network`
Quadlet. The runtime network name and private addresses are configurable.
Keycloak/PostgreSQL have no public listener; optional management is loopback-only.
NGINX terminates TLS and replaces forwarded headers. The configured trusted
proxy address must match NGINX's private address. TLS files and trust are
caller-owned. Rootless mode currently supports the xforwarded header contract.

## Dependencies

- `lit.foundational.kubeplay`
- `lit.foundational.podman_systemd`

## Example Playbook

```yaml
- name: Deploy Nginx
  hosts: web
  gather_facts: true
  roles:
    - role: nginx_deploy
  tags:
    - nginx
```

## License

MIT

## Author

Lightning IT
