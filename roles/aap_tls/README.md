# aap_tls

Generate temporary self-signed TLS assets for AAP when explicitly enabled.

## Variables

- `aap_tls_selfsigned_delegate_to`: host that persists the generated TLS files;
  defaults to `localhost` for controller-local generation.
- `aap_tls_selfsigned_output_dir`: writable output directory on the generation
  host. When `aap_tls_selfsigned_delegate_to` is not `localhost`, set this to a
  path writable on that delegated host; the controller-local default is not
  portable to another host.
