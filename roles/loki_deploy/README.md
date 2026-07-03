# loki_deploy

Deploy Loki as an internal technical logging backend with Podman Quadlet.

The role renders a Podman pod manifest and manages it through systemd Quadlet
when `loki_deploy_manage_systemd` is enabled. Non-systemd deployments can still
use the existing kubeplay path.

Loki binds to `127.0.0.1:3100` by default and is not exposed through NGINX
unless a caller explicitly changes the host binding and proxy configuration.

## Key Variables

| Variable | Default | Description |
|---|---|---|
| `loki_deploy_image` | `docker.io/grafana/loki:3.4.2` | Loki image. |
| `loki_deploy_host_data_dir` | `/srv/loki/data` | Persistent Loki data. |
| `loki_deploy_config_dir` | `/srv/loki/config` | Loki config directory. |
| `loki_deploy_host_ip` | `127.0.0.1` | Host bind address. |
| `loki_deploy_port` | `3100` | Loki HTTP port. |
| `loki_deploy_retention_period` | `168h` | Filesystem retention window. |
| `loki_deploy_expose_public` | `false` | Documentation guard; proxy exposure is opt-in. |

## Example

```yaml
- hosts: logging_hosts
  gather_facts: true
  become: true
  roles:
    - role: lit.supplementary.loki_deploy
```
