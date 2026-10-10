# vault_connection_credentials

Read existing KV v2 desktop-account documents through certificate-validated AppRole access. No credentials are generated, rewritten, or copied to another Vault path. The result is a RAM-only mapping for a consuming application.

Declare `vault_connection_credentials_sources` with `vault_path`, `subject`, `purpose`, `username`, `tier`, and `destination`. Documents require schema version 1 and an `accounts` list containing exactly one matching username and tier with a password of at least 32 characters. Supply `vault_connection_credentials_auth` with `url`, `ca_cert`, `namespace`, `auth_mount_point`, `role_id`, and `secret_id`, and the KV mount separately. Secret handling uses `no_log`.
