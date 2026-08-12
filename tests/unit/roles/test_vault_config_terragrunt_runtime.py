from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_vault_config_forwards_strict_import_mode():
    tasks = (ROOT / "roles/vault_config/tasks/config.yml").read_text(encoding="utf-8")

    assert ("terragrunt_import_strict: {{ terragrunt_import_strict | default(false) | bool | to_json }}") in tasks
    assert "terragrunt_state_moves: {{ vault_config_terragrunt_state_moves" in tasks
    assert "terragrunt_state_removals: {{ vault_config_terragrunt_state_removals" in tasks
    assert "terragrunt_state_migration_strict: {{" in tasks
    assert "terragrunt_state_migration_strict\n                | default(false)" in tasks
    assert "terragrunt_init_upgrade: {{ terragrunt_init_upgrade" in tasks
