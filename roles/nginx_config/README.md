# nginx_config

Manage Nginx virtual host configuration files for the Podman container deployment.

## Requirements

None.

## Role Variables

See `roles/nginx_config/defaults/main.yml` and `roles/nginx_deploy/defaults/main.yml`.

Key variables:
- `nginx_config_vhosts`
- `nginx_config_remove_default`

## Example Playbook

```yaml
- name: Configure Nginx vhosts
  hosts: web
  gather_facts: true
  roles:
    - role: nginx_config
      vars:
        nginx_config_vhosts:
          - name: app
            server_name: app.example.test
            root: /usr/share/nginx/html
            listen_port: 8080
  tags:
    - nginx
```
