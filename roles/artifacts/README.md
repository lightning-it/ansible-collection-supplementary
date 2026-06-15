# lit.supplementary.artifacts

Stage binary artifacts on managed hosts and verify them with checksums.

The role is intentionally provider-neutral. Hetzner Object Storage, AWS S3, MinIO,
or another S3-compatible backend can be used through HTTPS object URLs or
presigned URLs. The role does not need cloud credentials on the managed host.

## Requirements

- A reachable artifact URL, a controller-local source file, or an existing
  managed-host source file.
- A checksum for every production artifact.

## Variables

- `artifacts_enabled` (bool, default: `true`): Enable the role.
- `artifacts_items` (list, default: `[]`): Artifact definitions.
- `artifacts_default_owner` / `artifacts_default_group` (string): Default file ownership.
- `artifacts_default_mode` (string): Default file mode.
- `artifacts_default_directory_mode` (string): Default destination directory mode.
- `artifacts_default_force` (bool): Force downloads/copies even when a destination exists.
- `artifacts_default_validate_certs` (bool): Validate HTTPS certificates for URL downloads.
- `artifacts_default_timeout` (int): URL download timeout in seconds.
- `artifacts_default_no_log` (bool): Hide task arguments/results for sensitive URLs.

Each `artifacts_items` entry supports:

- `name`: Human-readable item name.
- `source`: `url`, `local`, or `remote` (default: `url`).
- `url`: HTTPS/presigned URL for `source: url`.
- `src`: Controller path for `source: local`, or managed-host path for `source: remote`.
- `remote_src`: Managed-host source path for `source: remote`.
- `dest`: Absolute destination path on the managed host.
- `checksum`: Checksum in Ansible format, for example `sha256:<hex>`.
- `headers`: Optional HTTP headers for URL downloads.
- `owner`, `group`, `mode`, `directory_mode`, `force`, `validate_certs`, `timeout`, `no_log`.

## Example

```yaml
---
- name: Stage AAP and Incus artifacts
  hosts: artifact_hosts
  become: true
  roles:
    - role: lit.supplementary.artifacts
      vars:
        artifacts_items:
          - name: aap-2.7-containerized-bundle
            source: url
            url: "{{ lookup('ansible.builtin.env', 'AAP_27_BUNDLE_URL') }}"
            dest: /srv/aap/bundles/aap-2.7-containerized-setup-bundle.tar.gz
            checksum: "sha256:{{ lookup('ansible.builtin.env', 'AAP_27_BUNDLE_SHA256') }}"
            no_log: true

          - name: rhel-10-incus-qcow2
            source: url
            url: "{{ lookup('ansible.builtin.env', 'RHEL_10_INCUS_QCOW2_URL') }}"
            dest: /srv/incus/images/rhel-10-cloud.qcow2
            checksum: "sha256:{{ lookup('ansible.builtin.env', 'RHEL_10_INCUS_QCOW2_SHA256') }}"
            no_log: true
```

## License

MIT
