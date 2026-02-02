# nginx_deploy

Deploy Nginx as a Podman container, similar to the Vault deployment pattern.

## Requirements

None.

## Role Variables

See `roles/nginx_deploy/defaults/main.yml`.

Key variables:
- `nginx_deploy_image`
- `nginx_deploy_pod_manifest_path`
- `nginx_deploy_host_conf_dir`
- `nginx_deploy_host_root`
- `nginx_deploy_listen_port`
- `nginx_deploy_manage_default_site`
- `nginx_deploy_manage_systemd`
- `nginx_deploy_selinux_relabel`
- `nginx_deploy_skip_runtime`

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
