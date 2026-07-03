# alertmanager_deploy

Deploy Alertmanager as a Podman container managed by systemd through Quadlet.

The role renders:

- an Alertmanager configuration file
- a Podman pod manifest
- a `.kube` Quadlet unit through `lit.foundational.podman_systemd`

## Example

```yaml
- role: lit.supplementary.alertmanager_deploy
  vars:
    alertmanager_deploy_host_ip: "0.0.0.0"
    alertmanager_deploy_port: 9093
    alertmanager_deploy_receivers:
      - name: default
```

## Key Variables

- `alertmanager_deploy_image`: Alertmanager container image.
- `alertmanager_deploy_config_dir`: host configuration directory.
- `alertmanager_deploy_data_dir`: host storage directory.
- `alertmanager_deploy_host_ip`: host bind address.
- `alertmanager_deploy_port`: host TCP port.
- `alertmanager_deploy_route`: Alertmanager route as structured YAML data.
- `alertmanager_deploy_receivers`: Alertmanager receivers as structured YAML data.

The default service binds to `127.0.0.1:9093`. Set
`alertmanager_deploy_host_ip` to another address only when the service should
be reachable externally.
