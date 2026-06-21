# checkmk_deploy

Deploy Checkmk as a monitoring service with Podman kube play.

This first implementation deploys Checkmk and writes a documented monitoring
target hook file at `{{ checkmk_deploy_config_dir }}/monitoring-targets.yml`.
Full Checkmk object provisioning is intentionally left for a later CaC role.

## Key Variables

| Variable | Default | Description |
|---|---|---|
| `checkmk_deploy_image` | `docker.io/checkmk/check-mk-raw:2.3.0-latest` | Checkmk image. |
| `checkmk_deploy_site_name` | `monitoring` | Checkmk site ID. |
| `checkmk_deploy_host_data_dir` | `/srv/checkmk/data` | Persistent site data. |
| `checkmk_deploy_port` | `5000` | Host port for Checkmk HTTP. |
| `checkmk_deploy_public_fqdn` | `checkmk.{{ inventory_hostname }}` | Reverse proxy hostname. |
| `checkmk_deploy_admin_user` | `cmkadmin` | Initial admin user. |
| `checkmk_deploy_admin_password` | `""` | Admin password, ideally from Ansible Vault. |
| `checkmk_deploy_vault_kv_path` | `{{ inventory_hostname }}/checkmk/admin` | HC Vault path. |
| `checkmk_deploy_monitoring_targets` | `[]` | Initial registration hook data. |

## Example

```yaml
- hosts: monitoring_hosts
  gather_facts: true
  become: true
  roles:
    - role: lit.supplementary.checkmk_deploy
```
