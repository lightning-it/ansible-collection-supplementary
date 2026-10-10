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
- `nginx_deploy_systemd_scope` (currently `system` only; `user` is rejected)
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

`nginx_deploy_host_network: true` permits a host-network Pod only with empty port bindings and empty attached networks. Its NGINX server configuration must declare explicit listen addresses. The default remains false with the existing port publication contract.
