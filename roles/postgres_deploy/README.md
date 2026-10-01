# postgres_deploy

Deploy PostgreSQL as a dedicated Podman pod on RHEL hosts.

## Requirements

None.

## Variables

See `roles/postgres_deploy/defaults/main.yml`.

Exactly one lifecycle controller owns the PostgreSQL pod. The container
configuration is rendered as Kubernetes YAML. With systemd management enabled,
the role hands that manifest to a native `.kube` Quadlet managed through
`lit.foundational.podman_systemd`; direct kubeplay mutation is disabled.
Without systemd management, the role uses one fail-closed kubeplay recreation.
An exact legacy `podman-kube@<escaped-manifest>.service` instance is stopped and
disabled once before native Quadlet takeover. A shared legacy template is not
removed because other services may still depend on it.
The default native unit is `<pod-name>-pod.service`, avoiding collisions with
an administrator-managed `postgres.service`. Enabling systemd management
without a detected systemd service manager fails during prechecks.

The generated Pod manifest is restricted to the owner (`0600`) because it
contains the effective PostgreSQL password required by the container runtime.

Key variables:
- `postgres_deploy_image`
- `postgres_deploy_pod_manifest_path`
- `postgres_deploy_host_data_dir`
- `postgres_deploy_port`
- `postgres_deploy_host_ip`
- `postgres_deploy_networks`
- `postgres_deploy_db_name`
- `postgres_deploy_db_user`
- `postgres_deploy_db_password`
- `postgres_deploy_generate_password`
- `postgres_deploy_manage_systemd`
- `postgres_deploy_readiness_retries`
- `postgres_deploy_readiness_delay`
- `postgres_deploy_skip_runtime`

## Dependencies

None.

## Example Playbook

```yaml
- name: Deploy PostgreSQL
  hosts: db_hosts
  become: true
  roles:
    - role: lit.supplementary.postgres_deploy
      vars:
        postgres_deploy_db_name: semaphore
        postgres_deploy_db_user: semaphore
```

## License

MIT

## Author

Lightning IT
