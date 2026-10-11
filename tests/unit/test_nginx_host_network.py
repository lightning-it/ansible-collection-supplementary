"""Reject ambiguous host-network deployment and retain published-port isolation."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.playbook.conditional import Conditional
from ansible.plugins.loader import init_plugin_loader
from ansible.template import Templar

ROOT = Path(__file__).resolve().parents[2] / "roles/nginx_deploy"


class HostNetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_plugin_loader()

    def values(self):
        return {
            **yaml.safe_load((ROOT / "defaults/main.yml").read_text()),
            "ansible_default_ipv4": {"address": "192.0.2.1"},
        }

    def accepts(self, values):
        gate = Conditional(loader=DataLoader())
        gate.when = yaml.safe_load((ROOT / "tasks/assert.yml").read_text())[0]["ansible.builtin.assert"]["that"]
        return gate.evaluate_conditional(Templar(DataLoader(), values), values)

    def test_explicit_host_network_has_no_publication_or_bridge(self):
        values = self.values()
        values.update(
            nginx_deploy_host_network=True,
            nginx_deploy_port_bindings=[],
            nginx_deploy_networks=[],
            nginx_deploy_manage_default_site=False,
        )
        self.assertTrue(self.accepts(values))
        pod = yaml.safe_load(Templar(DataLoader(), values).template((ROOT / "templates/nginx-pod.yml.j2").read_text()))
        self.assertIs(pod["spec"]["hostNetwork"], True)
        self.assertNotIn("ports", pod["spec"]["containers"][0])

    def test_conflicting_ports_and_bridges_fail_before_deployment(self):
        for change in (
            {"nginx_deploy_port_bindings": [{"container_port": 80, "host_port": 80}]},
            {"nginx_deploy_networks": ["extra.network"]},
        ):
            values = self.values()
            values.update(
                nginx_deploy_host_network=True,
                nginx_deploy_port_bindings=[],
                nginx_deploy_networks=[],
                nginx_deploy_manage_default_site=False,
            )
            values.update(change)
            self.assertFalse(self.accepts(values))

    def test_default_retains_publication_and_no_host_network(self):
        values = self.values()
        self.assertTrue(self.accepts(values))
        pod = yaml.safe_load(Templar(DataLoader(), values).template((ROOT / "templates/nginx-pod.yml.j2").read_text()))
        self.assertNotIn("hostNetwork", pod["spec"])
        self.assertGreater(len(pod["spec"]["containers"][0]["ports"]), 0)

    def test_host_network_cannot_render_a_wildcard_default_listener(self):
        values = self.values()
        values.update(nginx_deploy_host_network=True, nginx_deploy_port_bindings=[], nginx_deploy_networks=[])
        self.assertFalse(self.accepts(values))

    def test_real_transition_rejects_existing_and_linked_defaults_before_mutations(self):
        tasks = yaml.safe_load((ROOT / "tasks/assert.yml").read_text())
        selected = [
            task
            for task in tasks
            if task["name"].startswith(("Inspect previous default-site", "Refuse a retained default-site"))
        ]
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            default = base / "default.conf"
            retained = base / "retained.conf"
            marker = base / "deployment-started"
            config = base / "ansible.cfg"
            config.write_text("[defaults]\n")
            for kind in ("absent", "regular", "dangling-link", "alternate"):
                if default.is_symlink() or default.exists():
                    default.unlink()
                if retained.exists():
                    retained.unlink()
                if kind == "regular":
                    default.write_text("server { listen 80; }")
                elif kind == "dangling-link":
                    default.symlink_to(base / "missing")
                elif kind == "alternate":
                    retained.write_text("server { listen 80; }")
                for check in (False, True):
                    if marker.exists():
                        marker.unlink()
                    values = {
                        "nginx_deploy_host_network": True,
                        "nginx_deploy_host_conf_d_dir": str(base),
                        "nginx_deploy_host_default_conf_path": str(retained),
                    }
                    source = base / "play.yml"
                    source.write_text(
                        yaml.safe_dump(
                            [
                                {
                                    "hosts": "localhost",
                                    "gather_facts": False,
                                    "vars": values,
                                    "tasks": selected
                                    + [
                                        {
                                            "ansible.builtin.file": {
                                                "path": str(marker),
                                                "state": "touch",
                                                "mode": "0600",
                                            }
                                        }
                                    ],
                                }
                            ]
                        )
                    )
                    command = ["ansible-playbook", "-i", "localhost,", "-c", "local", str(source)]
                    if check:
                        command.append("--check")
                    result = subprocess.run(  # noqa: S603 - fixed local Ansible executable and controlled test fixture
                        command,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        env={**os.environ, "ANSIBLE_CONFIG": str(config), "ANSIBLE_LOCAL_TEMP": str(base / "ansible")},
                    )
                    self.assertEqual(result.returncode == 0, kind == "absent", result.stdout + result.stderr)
                    self.assertEqual(marker.exists(), kind == "absent" and not check)
                    if kind == "regular":
                        self.assertEqual(default.read_text(), "server { listen 80; }")
                    if kind == "dangling-link":
                        self.assertTrue(default.is_symlink())
                    if kind == "alternate":
                        self.assertEqual(retained.read_text(), "server { listen 80; }")
