"""Supplementary ownership and actual pilot caller boundaries."""

import hashlib
import json
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ASSETS = {
    ".github/workflows/copilot-review.yml",
    ".github/workflows/copilot-review-refresh.yml",
    ".github/workflows/current-revision-rerun.yml",
    ".github/workflows/review-event-reconcile.yml",
    ".github/workflows/dot-github-current-revision-required.yml",
    "scripts/review-event-reconcile.py",
    ".github/workflows/review-request-continuation.yml",
    "scripts/review_request_continuation.py",
    "scripts/review_request_provenance.py",
    "scripts/review_content_markers.py",
    "scripts/verify-dot-github-current-revision.py",
    "scripts/lit-push-ready.py",
    "tests/unit/test_dot_github_current_revision.py",
}


class PilotContractTests(unittest.TestCase):
    def test_scoped_inventory_binds_exact_assets_without_fleet_admission(self):
        inventory = json.loads((ROOT / ".lit/li219-managed-assets.json").read_text())
        source = json.loads((ROOT / ".lit/li219-pilot-source.json").read_text())
        self.assertEqual("li219-three-pilot", inventory["scope"])
        self.assertEqual("lightning-it/ansible-collection-supplementary", inventory["repository"])
        self.assertEqual(ASSETS, {asset["path"] for asset in inventory["assets"]})
        self.assertEqual(len(ASSETS), len(inventory["assets"]))
        self.assertEqual(ASSETS, {binding["target_path"] for binding in source["bindings"]})
        for binding in source["bindings"]:
            path = ROOT / binding["target_path"]
            self.assertFalse(path.is_symlink())
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(binding["target_sha256"], digest)
            asset = next(asset for asset in inventory["assets"] if asset["path"] == binding["target_path"])
            self.assertEqual(asset["sha256"], digest)
            if binding["mode"] == "byte-identical":
                self.assertEqual(binding["source_sha256"], digest)
                self.assertEqual("central-managed", asset["category"])
            else:
                self.assertEqual("local-required", asset["category"])
                self.assertEqual("ansible-collection-supplementary", asset["owner"])
        self.assertFalse((ROOT / ".github/workflows/supplementary-current-revision-required.yml").exists())

    def test_every_gateway_binding_binds_a_regular_target_and_source_identity(self):
        manifest = json.loads((ROOT / ".lit/li219-gateway-source.json").read_text())
        bindings = manifest["bindings"]
        self.assertGreater(len(bindings), 0)
        self.assertEqual(len(bindings), len({row["target_path"] for row in bindings}))
        for row in bindings:
            with self.subTest(target=row["target_path"]):
                target = ROOT / row["target_path"]
                self.assertFalse(target.is_symlink())
                self.assertTrue(target.is_file())
                self.assertTrue(target.resolve().is_relative_to(ROOT.resolve()))
                digest = hashlib.sha256(target.read_bytes()).hexdigest()
                self.assertEqual(row["target_sha256"], digest)
                self.assertIn(row["mode"], {"byte-identical", "adapted-local"})
                if row["mode"] == "byte-identical":
                    self.assertEqual(row["source_sha256"], digest)

    def test_producer_keeps_exact_source_and_separate_legacy_routes(self):
        text = (ROOT / ".github/workflows/copilot-review.yml").read_text()
        jobs = yaml.safe_load(text)["jobs"]
        request = jobs["request-current-revision-review"]
        environment = yaml.safe_load(text)["env"]
        for marker in ("PREMIUM_REQUEST_QUOTA_MARKER", "PREMIUM_REQUESTS_QUOTA_MARKER", "ERROR_REVIEW_MARKER"):
            self.assertIn(marker, environment)
        self.assertIn("github.run_attempt == 1", request["if"])
        self.assertIn("github.event.pull_request.user.login == 'litroc'", request["if"])
        self.assertIn('test "${TRUSTED_WORKFLOW_SHA}" = "${EXPECTED_BASE}"', text)
        self.assertIn('test "${TRUSTED_WORKFLOW_SHA}" = "${default_head}"', text)
        for name in ("develop", "main"):
            job = jobs[f"request-protected-verifier-reevaluation-{name}"]
            self.assertIn("LI219_EVENT_MODE", job["if"])
            self.assertIn("Inactive legacy", job["name"])
            self.assertIn(f"base.ref == '{name}'", job["if"])
        self.assertEqual(
            "lightning-it/ansible-collection-supplementary/.github/workflows/current-revision-rerun.yml"
            "@64451b42ec9d03c47ba8156f0952c139c0744648",
            jobs["request-protected-verifier-reevaluation-main"]["uses"],
        )
        event = jobs["dispatch-event-verifier-reevaluation"]
        self.assertIn("user.type == 'User'", event["if"])
        self.assertIn("LI219_EVENT_MODE", event["if"])
        self.assertIn("inputs[producer_run_attempt]", event["steps"][0]["run"])
        verifier = jobs["verify-current-revision-policy"]
        self.assertIn("user.login != 'lightning-it-release-automation[bot]'", verifier["if"])
        self.assertIn("backmerge/", verifier["if"])
        helper = yaml.safe_load((ROOT / ".github/workflows/current-revision-rerun.yml").read_text())["jobs"]
        for scope in ("contents", "checks"):
            self.assertEqual("read", helper["rerun-protected-verifier"]["permissions"][scope])
            self.assertEqual("write", helper["event-rerun"]["permissions"][scope])

    def test_continuation_keeps_local_topology_and_narrow_permissions(self):
        producer = yaml.safe_load((ROOT / ".github/workflows/copilot-review.yml").read_text())
        self.assertEqual(6, len(producer["jobs"]))
        request = producer["jobs"]["request-current-revision-review"]
        self.assertNotIn("needs", request)
        self.assertEqual(2, len(request["steps"]))
        self.assertEqual(
            {"actions": "read", "contents": "write", "issues": "write", "pull-requests": "write"},
            request["permissions"],
        )
        continuation = yaml.safe_load((ROOT / ".github/workflows/review-request-continuation.yml").read_text())
        self.assertEqual({"locate", "resume"}, set(continuation["jobs"]))
        self.assertEqual(
            {"actions": "write", "contents": "read", "pull-requests": "read", "issues": "read"},
            continuation["jobs"]["locate"]["permissions"],
        )
        self.assertEqual(
            {"actions": "read", "contents": "write", "pull-requests": "write", "issues": "read"},
            continuation["jobs"]["resume"]["permissions"],
        )
        self.assertEqual(2, len(continuation["jobs"]["resume"]["steps"]))
        reconcile = yaml.safe_load((ROOT / ".github/workflows/review-event-reconcile.yml").read_text())
        self.assertEqual("read", reconcile["permissions"]["issues"])
        provenance = (ROOT / "scripts/review_request_provenance.py").read_text()
        self.assertNotIn('"--method", "POST"', provenance)
        self.assertNotIn("def resume(", provenance)
        self.assertNotIn("def defer(", provenance)
        self.assertNotIn("createCommitOnBranch", provenance)

    def test_v3_classification_and_promotion_aggregation_remain_local(self):
        config = json.loads((ROOT / ".lit/push-ready.json").read_text())
        self.assertEqual(3, config["version"])
        self.assertEqual({"standard", "trust-root"}, set(config["review"]["profiles"]))
        self.assertEqual(2, config["review"]["classification"]["version"])
        self.assertEqual(500000, config["review"]["warn_diff_bytes"])
        verifier = (ROOT / "scripts/verify-dot-github-current-revision.py").read_text()
        self.assertIn("PROMOTION_TITLE", verifier)
        self.assertIn("def validate_aggregated_promotion(", verifier)
