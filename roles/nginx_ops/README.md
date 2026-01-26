# nginx_ops

Day-2 operational actions for Nginx (restart, reload, status, upgrade) for the Podman deployment.

## Requirements

None.

## Role Variables

See `roles/nginx_ops/defaults/main.yml` and `roles/nginx_deploy/defaults/main.yml`.

Key variables:
- `nginx_ops_action`: `restart`, `reload`, `status`, `upgrade`, or `none`.
- `nginx_ops_target_image`: container image for upgrade.

## Example Playbook

```yaml
- name: Restart Nginx
  hosts: web
  gather_facts: true
  roles:
    - role: nginx_ops
      vars:
        nginx_ops_action: restart
  tags:
    - ops
```
