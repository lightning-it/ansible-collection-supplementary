# samba

Meta/orchestrator role for the Samba lifecycle. There is intentionally no
`samba_cac` role by default because Samba is configured through local runtime
configuration files here, not API object reconciliation.
