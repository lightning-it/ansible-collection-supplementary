# lit.supplementary.aap_prepare

Prepare protected AAP runtime artifacts before deployment.

The role stages the AAP containerized setup bundle and subscription manifest on
the managed AAP host. It is intentionally independent from the Red Hat installer
workflow in `aap_deploy` and from API configuration in `aap_cac`.

## Sources

Each artifact can come from:

- `url`: HTTPS, presigned S3, Hetzner Object Storage, MinIO, or similar
- `local`: controller-local file
- `remote`: file already present on the managed host
- `auto`: explicit URL/local/remote value when set, otherwise exactly one
  matching file in `aap_prepare_artifact_dir`

## Defaults

- `aap_prepare_artifact_dir`: `${PWD}/.artifacts`
- setup bundle patterns:
  - `aap-containerized-setup.tar.gz`
  - `ansible-automation-platform-containerized-setup-bundle-*.tar.gz`
- manifest patterns:
  - `manifest*.zip`
  - `*manifest*.zip`

## Example

```yaml
aap_prepare_artifact_dir: "{{ lookup('ansible.builtin.env', 'PWD') }}/.artifacts"
aap_prepare_bundle_required: true
aap_prepare_manifest_required: true
aap_cac_controller_license_required: true
```

URL-backed example:

```yaml
aap_prepare_bundle_source: url
aap_prepare_bundle_url: "{{ vault_aap_bundle_url }}"
aap_prepare_bundle_checksum: "sha256:{{ vault_aap_bundle_sha256 }}"

aap_prepare_manifest_source: url
aap_prepare_manifest_url: "{{ vault_aap_manifest_url }}"
aap_prepare_manifest_checksum: "sha256:{{ vault_aap_manifest_sha256 }}"
```

After staging, the role publishes host facts consumed by downstream roles:

- `aap_deploy_setup_archive_path`
- `aap_cac_controller_license_manifest_remote_src`

## License

MIT
