from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def test_vault_config_forwards_strict_import_mode():
    defaults = yaml.safe_load((ROOT / "roles/vault_config/defaults/main.yml").read_text(encoding="utf-8"))
    tasks = (ROOT / "roles/vault_config/tasks/config.yml").read_text(encoding="utf-8")

    assert defaults["vault_config_terragrunt_import_strict"] is False
    assert defaults["vault_config_terragrunt_state_migration_strict"] is False
    assert defaults["vault_config_terragrunt_init_upgrade"] is False
    assert "terragrunt_import_strict: {{ vault_config_terragrunt_import_strict" in tasks
    assert "terragrunt_state_moves: {{ vault_config_terragrunt_state_moves" in tasks
    assert "terragrunt_state_removals: {{ vault_config_terragrunt_state_removals" in tasks
    assert "vault_config_terragrunt_state_migration_strict" in tasks
    assert "terragrunt_init_upgrade: {{ vault_config_terragrunt_init_upgrade" in tasks
