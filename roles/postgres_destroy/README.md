# postgres_destroy

Protected PostgreSQL teardown role. Destructive actions are disabled by default.
An executed destroy removes the persistent Quadlet service before removing the
pod manifest. Set `postgres_destroy_remove_systemd=false` only for an explicitly
managed external lifecycle controller.
