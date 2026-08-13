"""Regression tests for AAP self-signed CA trust installation."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class AapTlsContractsTests(unittest.TestCase):
    """Keep CA generation and target trust ownership separated."""

    def test_generated_ca_is_transferred_to_managed_host_trust(self) -> None:
        defaults = (ROOT / "roles/aap_tls/defaults/main.yml").read_text(encoding="utf-8")
        tasks = (ROOT / "roles/aap_tls/tasks/main.yml").read_text(encoding="utf-8")
        assertions = (ROOT / "roles/aap_tls/tasks/assert.yml").read_text(encoding="utf-8")
        handlers = (ROOT / "roles/aap_tls/handlers/main.yml").read_text(encoding="utf-8")

        self.assertIn("aap_tls_selfsigned_install_ca_trust: true", defaults)
        self.assertIn("Read temporary AAP CA from generation host", tasks)
        self.assertIn("aap_tls_selfsigned_ca_content.content | b64decode", tasks)
        self.assertIn("Install temporary AAP CA in target system trust store", tasks)
        self.assertNotIn("remote_src: true", tasks)
        self.assertNotIn("delegate_to:", handlers)
        self.assertIn("cmd: update-ca-trust extract", handlers)
        self.assertIn("ansible.builtin.meta: flush_handlers", tasks)
        precheck_entrypoint = "---\n- name: Prechecks\n  ansible.builtin.import_tasks: assert.yml\n  tags: always\n"
        self.assertTrue(tasks.startswith(precheck_entrypoint))
        self.assertIn("aap_tls_selfsigned_ca_trust_owner", assertions)
        self.assertIn("aap_tls_selfsigned_ca_trust_group", assertions)
        self.assertIn("is match('^[0-9]+$')", assertions)
        self.assertNotIn("is regex(", assertions)
        self.assertIn("aap_tls_selfsigned_ca_trust_become is boolean", assertions)
        self.assertIn("aap_tls_selfsigned_ca_trust_become is sameas true", assertions)
        self.assertIn("aap_tls_selfsigned_ca_trust_become is sameas false", assertions)
        self.assertIn("aap_tls_selfsigned_ca_trust_test_mode is sameas true", assertions)
        self.assertIn("aap_tls_selfsigned_ca_trust_test_mode is sameas false", assertions)
        self.assertIn("^/etc/pki/ca-trust/source/anchors/", assertions)
        self.assertIn("^/[A-Za-z0-9._/-]+$", assertions)
        self.assertNotIn("^/tmp/", assertions)
        self.assertNotIn("MOLECULE_EPHEMERAL_DIRECTORY", assertions)
        self.assertIn("ansible_connection == 'local'", assertions)
        self.assertLess(
            assertions.index("Require local controller before inspecting private AAP TLS test paths"),
            assertions.index("Inspect private AAP TLS test root, trust directory, and trust target"),
        )
        self.assertIn("_aap_tls_test_controller_uid.stdout | int > 0", assertions)
        self.assertIn("_aap_tls_test_controller_gid.stdout | int > 0", assertions)
        self.assertIn("== _aap_tls_test_controller_uid.stdout | int", assertions)
        self.assertIn("== _aap_tls_test_controller_gid.stdout | int", assertions)
        self.assertIn(".stat.gid | int", assertions)
        self.assertIn('- "{{ aap_tls_selfsigned_ca_trust_path }}"', assertions)
        self.assertIn("_aap_tls_test_path_stats.results[2].stat.islnk", assertions)
        self.assertIn("_aap_tls_test_path_stats.results[2].stat.isreg", assertions)
        self.assertIn("--canonicalize-existing", assertions)
        self.assertIn("not aap_tls_selfsigned_ca_trust_test_root.endswith('/')", assertions)
        self.assertIn("fail_msg:", assertions)
        self.assertNotIn("Validate temporary AAP CA trust installation settings", tasks)

    def test_invalid_trust_inputs_are_exercised_by_molecule(self) -> None:
        converge = (ROOT / "molecule/aap-tls-basic/converge.yml").read_text(encoding="utf-8")

        self.assertIn("MOLECULE_EPHEMERAL_DIRECTORY') }}/aap-tls", converge)
        self.assertIn("aap_tls_selfsigned_ca_trust_owner: invalid-owner", converge)
        self.assertIn('aap_tls_selfsigned_ca_trust_become: "false"', converge)
        self.assertIn("aap_tls_molecule_invalid_owner_rejected", converge)
        self.assertIn("aap_tls_molecule_invalid_become_rejected", converge)
        self.assertIn("aap_tls_molecule_zero_identity_rejected", converge)
        self.assertIn("aap_tls_molecule_mismatched_identity_rejected", converge)
        self.assertIn('aap_tls_selfsigned_ca_trust_owner: "0"', converge)
        self.assertIn("'id -u') | int + 1", converge)
        self.assertIn("'id -g') | int + 1", converge)
        self.assertIn("aap_tls_molecule_privileged_numeric_owner_rejected", converge)
        self.assertIn("unsafe privileged numeric ownership", converge)
        self.assertIn("aap_tls_molecule_forged_environment_rejected", converge)
        self.assertIn("aap_tls_molecule_non_local_test_mode_rejected", converge)
        self.assertIn("aap_tls_molecule_trailing_slash_root_rejected", converge)
        self.assertIn("aap_tls_molecule_symlink_parent_rejected", converge)
        self.assertIn("aap_tls_molecule_symlink_target_rejected", converge)
        self.assertIn("trust/aap-symlink-ca.crt", converge)

    def test_test_mode_defaults_fail_closed(self) -> None:
        defaults = (ROOT / "roles/aap_tls/defaults/main.yml").read_text(encoding="utf-8")

        self.assertIn("aap_tls_selfsigned_ca_trust_test_mode: false", defaults)
        self.assertIn('aap_tls_selfsigned_ca_trust_test_root: ""', defaults)


if __name__ == "__main__":
    unittest.main()
