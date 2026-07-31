# hetzner_object_storage_cac

Reconciles and audits private Hetzner Object Storage buckets through the
S3-compatible API. The role is fail-closed around HTTPS endpoints, versioning,
Object Lock at bucket creation, default retention, and incomplete multipart
upload cleanup. It never creates S3 credentials.

Classification: configuration as code. Maturity: experimental. Tiny contract
coverage is available; Heavy and Application Acceptance remain blocked on a
protected paid Hetzner Object Storage project.

## Requirements

- `ansible-core` matching `meta/runtime.yml`.
- The collection dependencies declared in `galaxy.yml`.
- `boto3` and `botocore` in the execution environment.
- Existing Hetzner S3 access and secret keys supplied explicitly or read from
  HashiCorp Vault.

## Variables

See `defaults/main.yml` for the complete contract. Important inputs are
`hetzner_object_storage_cac_action`, `endpoint`, `region`, `bucket`, `prefix`,
the Object Lock and lifecycle settings, and exactly one credential source.
Actions are `plan`, `audit`, and `reconcile`.

`plan` performs no API call. `audit` confirms that the bucket is visible.
`reconcile` creates or updates the private bucket, including Object Lock,
versioning, default retention, and incomplete multipart cleanup.

TLS verification is mandatory. Bucket deletion is deliberately outside this
role. Hetzner S3 keys are project-bound and must be managed separately with
least privilege and a protected source of truth.

## Dependencies

The role uses `amazon.aws`, `community.aws`, and optionally
`community.hashi_vault`; collection versions are declared in `galaxy.yml`.

## Example Playbook

```yaml
---
- name: Reconcile one protected Hetzner S3 bucket
  hosts: localhost
  gather_facts: false
  roles:
    - role: lit.supplementary.hetzner_object_storage_cac
      vars:
        hetzner_object_storage_cac_action: reconcile
        hetzner_object_storage_cac_endpoint: https://fsn1.your-objectstorage.com
        hetzner_object_storage_cac_region: fsn1
        hetzner_object_storage_cac_bucket: example-production-backup
        hetzner_object_storage_cac_prefix: host01
        hetzner_object_storage_cac_use_vault: true
        hetzner_object_storage_cac_vault_addr: https://vault.example.com
        hetzner_object_storage_cac_vault_token: "{{ protected_vault_token }}"
        hetzner_object_storage_cac_vault_kv_mount: infrastructure
        hetzner_object_storage_cac_vault_kv_path: object-storage/host01
```

## License

MIT

## Author

Lightning IT
