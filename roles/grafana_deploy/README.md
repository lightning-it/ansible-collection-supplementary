# grafana_deploy

Deploy Grafana as the UI for Loki log exploration.

The role provisions Loki as the default datasource and stores the local admin
password in HC Vault when Vault access is configured. Without HC Vault, provide
`grafana_deploy_admin_password` from Ansible Vault encrypted inventory.

## Key Variables

| Variable | Default | Description |
|---|---|---|
| `grafana_deploy_image` | `docker.io/grafana/grafana:11.5.2` | Grafana image. |
| `grafana_deploy_host_data_dir` | `/srv/grafana/data` | Persistent data. |
| `grafana_deploy_port` | `3002` | Host port for the Grafana container. |
| `grafana_deploy_public_fqdn` | `grafana.{{ inventory_hostname }}` | Reverse proxy hostname. |
| `grafana_deploy_loki_url` | `http://127.0.0.1:3100` | Loki datasource URL. |
| `grafana_deploy_admin_user` | `admin` | Local admin user. |
| `grafana_deploy_admin_password` | `""` | Admin password, ideally from Ansible Vault. |
| `grafana_deploy_vault_kv_path` | `{{ inventory_hostname }}/grafana/admin` | HC Vault path. |

## Example

```yaml
- hosts: logging_hosts
  gather_facts: true
  become: true
  roles:
    - role: lit.supplementary.grafana_deploy
```
