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
        handlers = (ROOT / "roles/aap_tls/handlers/main.yml").read_text(encoding="utf-8")

        self.assertIn("aap_tls_selfsigned_install_ca_trust: true", defaults)
        self.assertIn("Read temporary AAP CA from generation host", tasks)
        self.assertIn("aap_tls_selfsigned_ca_content.content | b64decode", tasks)
        self.assertIn("Install temporary AAP CA in target system trust store", tasks)
        self.assertNotIn("remote_src: true", tasks)
        self.assertNotIn("delegate_to:", handlers)
        self.assertIn("cmd: update-ca-trust extract", handlers)
        self.assertIn("ansible.builtin.meta: flush_handlers", tasks)


if __name__ == "__main__":
    unittest.main()
