# aap_cac

AAP configuration-as-code role tasksets for AAP object configuration.

## Requirements

Install collections from:
- `collections/requirements.yml`

## Variables

Key variables:
- `aap_cac_collections_requirements`
- `aap_cac_gateway_hostname`
- `aap_cac_object_reconcile_orgs`
- `aap_cac_object_reconcile_secure_logging`
- `aap_cac_object_reconcile_protect_not_empty_orgs`

## Notes

- Role tasksets are self-contained under `roles/aap_cac/tasks`.
- OAuth token helper tasks are part of the role:
  - `tasks/create_authentication_token.yml`
  - `tasks/delete_authentication_token.yml`
- Full CaC entrypoint taskset:
  - `tasks/main.yml`
- Composite subset entrypoint (Hub sync):
  - `tasks/cac_34_sync_hub.yml`
  - Not auto-included by `tasks/main.yml` to avoid duplicate execution.
- Pattern example: call role task entrypoints directly, e.g.
  `roles/aap_cac/tasks/cac_11_gateway_organizations.yml`.

## Dependencies

None.

## License

GPL-3.0-only

## Author

Lightning IT
