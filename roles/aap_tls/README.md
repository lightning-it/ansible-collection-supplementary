# aap_tls

Generate temporary self-signed TLS assets for AAP. Self-signed generation is
enabled by default; set `aap_tls_selfsigned_enabled: false` when customer TLS
assets are supplied instead.

## Requirements

- Ansible and the role dependencies declared by this collection.
- A writable `aap_tls_selfsigned_output_dir` on the host selected for
  generation.
- The RHEL `ca-certificates` package and `update-ca-trust` command on the
  managed AAP host when target trust installation is enabled. The AAP base-OS
  preparation owns this prerequisite.

## Variables

- `aap_tls_selfsigned_delegate_to`: host that persists the generated TLS files;
  defaults to `localhost` for controller-local generation.
- `aap_tls_selfsigned_output_dir`: writable output directory on the generation
  host. When `aap_tls_selfsigned_delegate_to` is not `localhost`, set this to a
  path writable on that delegated host; the controller-local default is not
  portable to another host.
- `aap_tls_selfsigned_enabled`: enables self-signed asset generation; defaults
  to `true`.
- `aap_tls_selfsigned_install_ca_trust`: installs the generated CA in the
  managed AAP host trust store and refreshes system trust; defaults to `true`.
  Generation may remain delegated to the controller because the role transfers
  the public CA certificate to the managed host before installation.

See [`defaults/main.yml`](defaults/main.yml) for the complete interface.

## Dependencies

None.

## Example Playbook

```yaml
- hosts: aap
  roles:
    - role: lit.supplementary.aap_tls
```

## License

MIT

## Author

Lightning IT Platform Engineering
