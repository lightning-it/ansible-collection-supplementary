# lit.supplementary.cloudflare_warp

Install and manage the Cloudflare WARP client for Zero Trust device
connectivity.

This role is intentionally separate from `lit.supplementary.cloudflared`.
`cloudflared` manages Cloudflare Tunnel connectors, while this role manages the
device-side WARP client, its MDM enrollment profile, the `warp-svc` daemon, and
the desired connection state.

## Variables

Primary toggles:

- `cloudflare_warp_enabled`: Enable the role (default: `false`).
- `cloudflare_warp_install`: Install the package (default: `true`).
- `cloudflare_warp_manage_service`: Ensure `warp-svc` is enabled and started
  (default: `true`).
- `cloudflare_warp_configure_mdm`: Render `/var/lib/cloudflare-warp/mdm.xml`
  (default: `true`).
- `cloudflare_warp_connection_state`: Desired runtime state:
  `connected`, `disconnected`, or `ignore` (default: `connected`).

Required when `cloudflare_warp_configure_mdm: true`:

- `cloudflare_warp_organization`: Zero Trust organization/team name.
- `cloudflare_warp_auth_client_id`: Service token client ID.
- `cloudflare_warp_auth_client_secret`: Service token client secret.

Useful optional variables:

- `cloudflare_warp_service_mode`: MDM service mode. Supported values:
  `warp`, `1dot1`, `proxy`, `postureonly`, `tunnelonly`.
- `cloudflare_warp_auto_connect`: Auto-connect timer in seconds (default: `1`).
- `cloudflare_warp_onboarding`: Show onboarding in the client UI
  (default: `false`).
- `cloudflare_warp_switch_locked`: Prevent local users from disabling WARP
  (default: `false`).
- `cloudflare_warp_gateway_unique_id`: Optional Gateway DoH location override.
- `cloudflare_warp_support_url`: Optional help URL or `mailto:` target.
- `cloudflare_warp_show_status`: Run a final `warp-cli status` check
  (default: `false`).

## Example

```yaml
- hosts: workbenches
  become: true
  roles:
    - role: lit.supplementary.cloudflare_warp
      vars:
        cloudflare_warp_enabled: true
        cloudflare_warp_organization: "{{ vault_cloudflare_warp_organization }}"
        cloudflare_warp_auth_client_id: "{{ vault_cloudflare_warp_auth_client_id }}"
        cloudflare_warp_auth_client_secret: "{{ vault_cloudflare_warp_auth_client_secret }}"
        cloudflare_warp_service_mode: warp
        cloudflare_warp_connection_state: connected
```

## Notes

- Use a service token with Service Auth device enrollment permissions.
- The role manages the Linux MDM file at `/var/lib/cloudflare-warp/mdm.xml`
  following Cloudflare's headless Linux deployment model.
- The RPM package itself installs the `warp-svc` systemd unit; the role keeps
  the service state explicit and idempotent in Ansible.
