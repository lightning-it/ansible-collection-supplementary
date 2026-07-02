# postgres

Meta/orchestrator role for the PostgreSQL lifecycle.

It composes preflight, deploy, config, validation, operations, backup/restore,
upgrade, and destroy roles. There is intentionally no `postgres_cac` role by
default; add one only when PostgreSQL has real declarative object
reconciliation.
