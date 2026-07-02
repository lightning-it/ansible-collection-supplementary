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

Use this role from runbooks instead of copying checks into customer guides.

## License

MIT
