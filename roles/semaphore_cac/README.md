# semaphore_cac

Configuration-as-Code orchestration role for Semaphore UI.

This role intentionally separates object/API orchestration concerns from runtime deployment
(`semaphore_deploy`), following the `_cac` role split used across the collection.

## Behavior

- `semaphore_cac_skip_apply: true` (default): no-op
- `semaphore_cac_skip_apply: false`: runs API preflight and all discovered `cac_*.yml` tasksets

## Key variables

- `semaphore_cac_skip_apply`
- `semaphore_cac_url`
- `semaphore_cac_admin_login`
- `semaphore_cac_admin_password`

## Taskset convention

Taskset files are discovered automatically from `tasks/cac_*.yml`.
Add additional `cac_*.yml` files to extend object reconciliation flows.
