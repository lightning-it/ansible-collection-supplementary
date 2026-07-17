# lit.supplementary.aap_preflight

Validate AAP setup prerequisites before prepare or deploy.

The role checks the operational contract for local execution:

- setup/runbooks connect as `svc_ansible` by default
- AAP runtime/install user is `svc_aap` by default
- setup user can become root without an interactive password prompt
- `/appl` substrate paths are present and traversable by service users
- required tools and Podman are available
- first-install runtime state is clean
- remote artifact sources exist
- either HashiCorp Vault or Ansible Vault secrets are usable

When `aap_preflight_check_prepared_host` is enabled, it also validates the
declared RHEL version and architecture, FQDN, SELinux, time synchronization,
CPU/RAM, the `/appl` filesystem and inode threshold, temporary capacity,
packages, ansible-core version, BaseOS/AppStream labels, CA bundle, and
subordinate IDs. It reports `RHEL9_PREPARED_HOST_GATE_OK` without remediating
the customer baseline.

When `aap_preflight_check_execution_environment` is enabled, the role requires
an approved repository with either a fixed non-`latest` version or a lowercase
SHA-256 digest, trusted registry HTTPS, and availability of the selected
manifest. It never builds or mirrors an image and reports
`AAP_EXECUTION_ENVIRONMENT_VALIDATED_OK` on success.

Use this role from runbooks instead of copying checks into customer guides.

## License

MIT
