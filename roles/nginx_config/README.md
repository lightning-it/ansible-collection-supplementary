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
- `nginx_config_tls_source` (`vault`, `file`, or `selfsigned`, default: `vault`)
- `nginx_config_tls_certificate`
- `nginx_config_tls_certificate_key`
- `nginx_config_tls_certificate_file_source`
- `nginx_config_tls_certificate_key_file_source`
- `nginx_config_tls_file_remote_src`
- `nginx_config_vault_address`
- `nginx_config_vault_ca_cert`
- `nginx_config_vault_namespace`
- `nginx_config_vault_auth_mount_point`
- `nginx_config_vault_kv_mount`
- `nginx_config_vault_kv_path`
- `nginx_config_vault_pki_path`
- `nginx_config_vault_pki_role`
- `nginx_config_vault_issue_missing` (default: `true`; issue and persist missing or mismatched material through Vault PKI)
- `nginx_config_vault_allow_local_fallback` (default: `false`; an explicit migration-only escape hatch)
- `nginx_config_waf_enabled` (default: `false`)
- `nginx_config_waf_server_directives`
- `nginx_config_waf_location_directives`
- `nginx_config_remove_default`

With `nginx_config_tls_source: vault`, certificate material is read from Vault
KV or issued through Vault PKI and then persisted to Vault KV. Private keys are
written to the managed host with mode `0600`. Local certificate/key files are
not accepted as a fallback by default. A migration that intentionally imports
existing host files must opt in explicitly and must not be used as proof of
Vault custody.

`nginx_config_waf_enabled` turns the reverse proxy into an explicit policy-WAF
boundary by applying the supplied server controls and location controls to
every generated TLS proxy vhost. Rate/connection zones used by those controls
must be declared in `nginx_deploy_http_extra_directives`. This baseline uses
NGINX-native controls; signature inspection such as OWASP CRS requires a
separately reviewed ModSecurity/Coraza integration.

The default reverse-proxy contract overwrites `Host`, `X-Real-IP`, and every
Keycloak-relevant `X-Forwarded-*` identity header from NGINX-owned connection
state. It strips `Forwarded`, `X-Original-Forwarded-For`, and
`X-Forwarded-Prefix` so an Internet client cannot inject a second trusted
identity chain. Custom `proxy_directives` replace the defaults and therefore
must preserve the same overwrite-and-strip contract.

When `nginx_config_vault_issue_missing: false`, Vault KV must already contain a
certificate/private-key pair, a CA chain, and matching common-name and
alternative-name metadata. Local host files do not satisfy that stored-identity
contract.

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
              - "proxy_set_header X-Forwarded-For $remote_addr"
              - "proxy_set_header X-Forwarded-Host $server_name"
              - "proxy_set_header X-Forwarded-Port $server_port"
              - "proxy_set_header X-Forwarded-Proto $scheme"
              - 'proxy_set_header X-Forwarded-Prefix ""'
              - 'proxy_set_header X-Original-Forwarded-For ""'
              - 'proxy_set_header Forwarded ""'
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

MIT

## Author

Lightning IT
