# nginx_validate

Validate Nginx runtime and configuration state without changing configuration for the Podman deployment.

## Requirements

None.

## Role Variables

See `roles/nginx_validate/defaults/main.yml` and `roles/nginx_deploy/defaults/main.yml`.

Key variables:
- `nginx_validate_mode`: `fail` (default) or `report`.
- `nginx_validate_check_config`
- `nginx_validate_check_http`
- `nginx_deploy_skip_validate`

## Example Playbook

```yaml
- name: Validate Nginx
  hosts: web
  gather_facts: true
  roles:
    - role: nginx_validate
  tags:
    - validate
```
