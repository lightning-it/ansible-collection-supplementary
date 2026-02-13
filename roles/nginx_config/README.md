# nginx_config

Manage Nginx virtual host configuration files for the Podman container deployment.

## Requirements

None.

## Variables

See `roles/nginx_config/defaults/main.yml` and `roles/nginx_deploy/defaults/main.yml`.

Key variables:
- `nginx_config_vhosts`
- `nginx_config_service_vhosts_enabled`
- `nginx_config_service_vhosts`
- `nginx_config_tls_source` (`vault` or `selfsigned`, default: `vault`)
- `nginx_config_tls_certificate`
- `nginx_config_tls_certificate_key`
- `nginx_config_vault_address`
- `nginx_config_vault_kv_mount`
- `nginx_config_vault_kv_path`
- `nginx_config_vault_pki_path`
- `nginx_config_vault_pki_role`
- `nginx_config_remove_default`

## Dependencies

None.

## Example Playbook

```yaml
- name: Configure Nginx vhosts
  hosts: web
  gather_facts: true
  roles:
    - role: nginx_config
      vars:
        nginx_config_service_vhosts_enabled: true
        nginx_config_tls_source: vault
        nginx_config_tls_certificate: /etc/nginx/certs/fullchain.pem
        nginx_config_tls_certificate_key: /etc/nginx/certs/privkey.pem
        nginx_config_service_vhosts:
          - name: vault
            server_name: vault.prd.dmz.corp.l-it.io
            upstream_url: https://vault:8200
            proxy_directives:
              - "proxy_set_header Host vault.prd.dmz.corp.l-it.io"
              - "proxy_set_header X-Real-IP $remote_addr"
              - "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for"
              - "proxy_set_header X-Forwarded-Proto https"
              - "proxy_http_version 1.1"
              - "proxy_ssl_server_name on"
              - "proxy_ssl_name vault.prd.dmz.corp.l-it.io"
              - "proxy_ssl_verify off"
            force_https: true
          - name: nexus
            server_name: nexus.prd.dmz.corp.l-it.io
            upstream_url: http://nexus:8081
            force_https: true
          - name: minio
            server_name: minio.prd.dmz.corp.l-it.io
            upstream_url: http://minio:9000
            force_https: true
  tags:
    - nginx
```

## License

GPL-3.0-only

## Author

Lightning IT
