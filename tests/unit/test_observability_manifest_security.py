"""Regression tests for secret-bearing observability Pod manifests."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class ObservabilityManifestSecurityTests(unittest.TestCase):
    def test_secret_bearing_manifests_are_root_only_and_redacted(self) -> None:
        contracts = (
            (
                "grafana_deploy",
                "Render Grafana Pod manifest",
                "grafana-pod.yml.j2",
                "{{ grafana_deploy_pod_manifest_path }}",
                "GF_SECURITY_ADMIN_PASSWORD",
                "{{ grafana_deploy_admin_password_effective }}",
            ),
            (
                "checkmk_deploy",
                "Render Checkmk Pod manifest",
                "checkmk-pod.yml.j2",
                "{{ checkmk_deploy_pod_manifest_path }}",
                "CMK_PASSWORD",
                "{{ checkmk_deploy_admin_password_effective }}",
            ),
        )

        for role, task_name, source, destination, environment_name, secret_binding in contracts:
            with self.subTest(role=role):
                role_root = ROOT / "roles" / role
                writers: list[dict[str, object]] = []
                for task_path in sorted((role_root / "tasks").glob("*.yml")):
                    tasks = yaml.safe_load(task_path.read_text(encoding="utf-8"))
                    for task in tasks:
                        for module in ("ansible.builtin.template", "ansible.builtin.copy"):
                            parameters = task.get(module)
                            if isinstance(parameters, dict) and parameters.get("dest") == destination:
                                writers.append(task)

                self.assertEqual(1, len(writers), "secret-bearing manifest must have exactly one writer")
                task = writers[0]
                self.assertEqual(task_name, task.get("name"))
                template = task["ansible.builtin.template"]
                self.assertEqual(source, template.get("src"))
                self.assertEqual(destination, template.get("dest"))
                self.assertEqual("root", template.get("owner"))
                self.assertEqual("root", template.get("group"))
                self.assertEqual("0600", template.get("mode"))
                self.assertIs(task.get("no_log"), True)
                template_text = (role_root / "templates" / source).read_text(encoding="utf-8")
                self.assertIn(environment_name, template_text)
                self.assertIn(secret_binding, template_text)


if __name__ == "__main__":
    unittest.main()
