KEYCLOAK_COMPOSE := tests/keycloak/docker-compose.yml
KEYCLOAK_INVENTORY := tests/keycloak/inventory.keycloak_local.yml
KEYCLOAK_CHECK_PLAYBOOK := tests/keycloak/keycloak_check.yml

.PHONY: keycloak-up keycloak-down wait-keycloak check-keycloak

keycloak-up:
	docker compose -f $(KEYCLOAK_COMPOSE) up -d

keycloak-down:
	docker compose -f $(KEYCLOAK_COMPOSE) down -v

wait-keycloak:
	@echo "Waiting for Keycloak to become ready on http://localhost:9000/health/ready..."
	@until curl -sf http://localhost:9000/health/ready > /dev/null; do \
		printf "."; \
		sleep 3; \
	done; \
	echo " Keycloak is ready."

check-keycloak: keycloak-up wait-keycloak
	bash scripts/wunder-devtools-ee.sh ansible-playbook \
	  -i $(KEYCLOAK_INVENTORY) \
	  $(KEYCLOAK_CHECK_PLAYBOOK)
	$(MAKE) keycloak-down
