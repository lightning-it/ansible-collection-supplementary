# prometheus_deploy

Deploy Prometheus as a Podman container managed by systemd through Quadlet.

The role renders:

- a Prometheus configuration file
- an optional alerting rules file
- a Podman pod manifest
- a `.kube` Quadlet unit through `lit.foundational.podman_systemd`

## Example

```yaml
- role: lit.supplementary.prometheus_deploy
  vars:
    prometheus_deploy_host_ip: "0.0.0.0"
    prometheus_deploy_port: 9090
    prometheus_deploy_alertmanager_targets:
      - "127.0.0.1:9093"
    prometheus_deploy_scrape_configs:
      - job_name: prometheus
        static_configs:
          - targets:
              - "127.0.0.1:9090"
```

## Key Variables

- `prometheus_deploy_image`: Prometheus container image.
- `prometheus_deploy_config_dir`: host configuration directory.
- `prometheus_deploy_data_dir`: host TSDB directory.
- `prometheus_deploy_host_ip`: host bind address.
- `prometheus_deploy_port`: host TCP port.
- `prometheus_deploy_scrape_configs`: Prometheus scrape configs as structured YAML data.
- `prometheus_deploy_alertmanager_targets`: Alertmanager targets.

The default service binds to `127.0.0.1:9090`. Set `prometheus_deploy_host_ip`
to another address only when the service should be reachable externally.
