# alloy_deploy

Deploy Grafana Alloy as a local log collector with Podman Quadlet.

The role renders a Podman pod manifest and manages it through systemd Quadlet
when `alloy_deploy_manage_systemd` is enabled. Non-systemd deployments can
still use the existing kubeplay path.

By default Alloy ships journald, container logs, and common service log paths
under `/srv` to Loki. Vault audit logs are intentionally disabled by default;
set `alloy_deploy_collect_vault_audit_logs: true` only after confirming the
audit log content is safe for the PoC logging backend.

## Key Variables

| Variable | Default | Description |
|---|---|---|
| `alloy_deploy_image` | Tag-and-digest reference in `meta/source-dependencies.yml` | Immutable Alloy image. |
| `alloy_deploy_config_dir` | `/srv/alloy/config` | Rendered River config. |
| `alloy_deploy_data_dir` | `/srv/alloy/data` | Alloy storage path. |
| `alloy_deploy_loki_url` | `http://127.0.0.1:3100/loki/api/v1/push` | Loki push endpoint. |
| `alloy_deploy_collect_journald` | `true` | Collect systemd journal logs. |
| `alloy_deploy_collect_vault_audit_logs` | `false` | Include Vault audit logs. |
| `alloy_deploy_extra_log_paths` | `[]` | Additional file sources. |

## Example

```yaml
- hosts: logging_hosts
  gather_facts: true
  become: true
  roles:
    - role: lit.supplementary.alloy_deploy
```
