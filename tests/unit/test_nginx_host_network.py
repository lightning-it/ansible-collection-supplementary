"""Reject ambiguous host-network deployment and retain published-port isolation."""

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
        values.update(nginx_deploy_host_network=True, nginx_deploy_port_bindings=[], nginx_deploy_networks=[])
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
            values.update(nginx_deploy_host_network=True, nginx_deploy_port_bindings=[], nginx_deploy_networks=[])
            values.update(change)
            self.assertFalse(self.accepts(values))

    def test_default_retains_publication_and_no_host_network(self):
        values = self.values()
        self.assertTrue(self.accepts(values))
        pod = yaml.safe_load(Templar(DataLoader(), values).template((ROOT / "templates/nginx-pod.yml.j2").read_text()))
        self.assertNotIn("hostNetwork", pod["spec"])
        self.assertGreater(len(pod["spec"]["containers"][0]["ports"]), 0)
