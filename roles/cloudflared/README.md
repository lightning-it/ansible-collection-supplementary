# lit.supplementary.cloudflared

Install and manage a Cloudflare Tunnel using `cloudflared` and a tunnel token.

## Variables

Required:

- `cloudflared_tunnel_token`: Tunnel token (string).

Optional:

- `cloudflared_no_log`: Hide token output (default: `true`).
- `cloudflared_repo_url`: Repo URL for RHEL (default: Cloudflare repo).
- `cloudflared_repo_path`: Repo path on RHEL (default: `/etc/yum.repos.d/cloudflared.repo`).
- `cloudflared_manage_repo`: Manage the RHEL repo file (default: `true`).
- `cloudflared_install`: Install the package (default: `true`).
- `cloudflared_manage_service`: Install and manage the systemd service (default: `true`).
- `cloudflared_package_state`: Package state (default: `present`).
- `cloudflared_update_cache`: Update package cache (default: `true`).
- `cloudflared_service_name`: Service name (default: `cloudflared`).
- `cloudflared_show_status`: Show `systemctl` status (default: `false`).

## Example

```yaml
- hosts: gateways
  become: true
  roles:
    - role: lit.supplementary.cloudflared
      vars:
        cloudflared_tunnel_token: "{{ vault_cloudflared_tunnel_token }}"
        cloudflared_show_status: true
```
