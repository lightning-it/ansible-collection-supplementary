# hetzner_object_storage_cac

Reconciles and audits private Hetzner Object Storage buckets through the
S3-compatible API. The role is fail-closed around HTTPS endpoints, versioning,
Object Lock at bucket creation, default retention, and incomplete multipart
upload cleanup. It never creates S3 credentials.

Classification: configuration as code. Maturity: compatibility role pending
migration to `lit.cloud.hetzner_object_storage`. Tiny contract coverage is
available; Heavy and Application Acceptance are centrally owned by
`lightning-it/modulix-validation`.

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

`bucket_project_id` identifies the project that owns the bucket.
`external_principals` is an optional list whose entries contain exactly
`name`, `project_id`, `access_key`, and `profile`. Principal projects must be
different from the bucket project. Hetzner documents that same-project keys
have default read/write access to every current and future bucket in that
project; this role therefore rejects them as non-least-privilege.

Profiles are fixed and cannot be extended through inventory:

- `admin`: bucket and object administration (`s3:*`), for separately protected
  administrative identities only.
- `writer`: upload and multipart completion/cleanup; it cannot read or delete
  objects and cannot read or change bucket policy or retention.
- `reader`: list and read current/versioned objects; it cannot write, delete,
  change policy, or change retention.
- `reviewer`: inspect bucket versioning/Object Lock state and object
  retention/legal-hold metadata; it cannot read object bodies or mutate
  objects, policy, or retention.

An empty list preserves the original bucket-only Plan/Audit/Reconcile contract
and does not manage a bucket policy. When principals are declared, the role
renders one deterministic bucket policy with the Hetzner-documented principal
form `arn:aws:iam:::user/p<project_id>:<access_key>`. Sanitized results expose
only the selected profile names and a policy SHA-256 digest, never secrets or
the access keys embedded in the policy.

Principal syntax and the separate-project least-privilege model follow the
[Hetzner S3 credentials FAQ](https://docs.hetzner.com/storage/object-storage/faq/s3-credentials/).

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
        hetzner_object_storage_cac_bucket_project_id: "10001"
        hetzner_object_storage_cac_external_principals:
          - name: backup-writer
            project_id: "20001"
            access_key: "{{ protected_writer_access_key }}"
            profile: writer
        hetzner_object_storage_cac_use_vault: true
        hetzner_object_storage_cac_vault_addr: https://vault.example.com
        hetzner_object_storage_cac_vault_token: "{{ protected_vault_token }}"
        hetzner_object_storage_cac_vault_kv_mount: infrastructure
        hetzner_object_storage_cac_vault_kv_path: object-storage/host01
```

## Compatibility and deprecation

The public variables, action behavior, sanitized result, Vault lookup contract,
and fail-closed validation documented here are frozen for migration. The old
FQCN remains supported until a released `lit.cloud.hetzner_object_storage`
replacement exists and a major-version removal window has been announced. It
must not be removed or silently redirected before that window.

## License

MIT

## Author

Lightning IT
