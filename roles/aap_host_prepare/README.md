# aap_host_prepare

Apply AAP-owned host changes after the customer-managed OS baseline has passed
preflight and before deploying AAP.

## Requirements

The target must be a supported RHEL host reachable by Ansible. Customer-owned
operating-system prerequisites should be validated before this role runs. Any
RHSM, repository, package, user, or Podman management must be enabled
explicitly by the calling runbook.

## Variables

See `defaults/main.yml` for the complete role interface. The role maps the AAP
install user, home, and shell into `aap_host_prepare_*_effective` values. The
calling runbook controls optional host changes through the existing
`aap_runbook_manage_*` variables.

## Dependencies

Optional host operations use roles from `lit.rhel` and the remote temporary
directory bootstrap uses `lit.foundational.ansible_remote_tmp`. Collection
dependencies are declared in `galaxy.yml`.

## Example Playbook

```yaml
- name: Apply AAP-owned host preparation
  hosts: aap
  become: true
  roles:
    - role: lit.supplementary.aap_host_prepare
      vars:
        aap_runbook_manage_rhsm: false
        aap_runbook_manage_repos: false
```

## License

MIT

## Author

Lightning IT
