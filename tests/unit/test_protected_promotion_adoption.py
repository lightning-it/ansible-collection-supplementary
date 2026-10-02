"""Bind the repo-local LI-139 adoption to the already reviewed central promoter.

Source: lightning-it/shared-assets-lit@b3c96a1e8164caaa7313d05998677a883f00e2e1
Path: .github/workflows/promote-develop-to-main.yml
The canonical mutation code is unchanged. Rendering retains the repo's
protected-main relay and approval environment, plus its exact identity binding.
"""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/promote-develop-to-main.yml"
SOURCE_SHA256 = "370e755f7106a68e7aa10cf1f7a42f3cb4170bd4ea896e68da75b510606d5d00"
TARGET = "lightning-it/ansible-collection-supplementary"
MAIN_CONDITION = (
    "    if: >-\n"
    f"      github.repository == '{TARGET}' &&\n"
    "      github.event_name == 'workflow_dispatch' &&\n"
    "      github.ref == 'refs/heads/main'\n"
)


class ProtectedPromotionAdoptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = WORKFLOW.read_text(encoding="utf-8")
        self.workflow = yaml.safe_load(self.text)
        self.job = self.workflow["jobs"]["promote"]
        self.script = self.job["steps"][-1]["run"]

    def test_adoption_preserves_canonical_mutation_code(self) -> None:
        self.assertEqual(self.text.count(MAIN_CONDITION), 1)
        relay_start = self.text.index("  dispatch:\n")
        relay_end = self.text.index("  promote:\n", relay_start)
        canonical = (self.text[:relay_start] + self.text[relay_end:]).replace(
            "# Repository-local adoption from lightning-it/shared-assets-lit.",
            "# Managed by lightning-it/shared-assets-lit.",
            1,
        ).replace(
            MAIN_CONDITION, "    if: github.repository == 'lightning-it/shared-assets-lit'\n", 1
        ).replace("    environment: ansible-collection-release-prepare\n", "", 1)
        self.assertEqual(hashlib.sha256(canonical.encode("utf-8")).hexdigest(), SOURCE_SHA256)

    def test_repository_and_credentials_are_narrowly_bound(self) -> None:
        self.assertEqual(set(self.workflow["jobs"]), {"dispatch", "promote"})
        self.assertEqual(
            self.job["if"],
            f"github.repository == '{TARGET}' && "
            "github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main'",
        )
        self.assertEqual(self.job["environment"], "ansible-collection-release-prepare")
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        mint = self.job["steps"][1]
        self.assertEqual(mint["uses"], "actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1")
        self.assertEqual(mint["with"]["repositories"], "${{ github.event.repository.name }}")
        self.assertEqual(mint["with"]["permission-contents"], "read")
        self.assertEqual(mint["with"]["permission-pull-requests"], "write")
        self.assertNotIn("permission-actions", mint["with"])

    def test_relay_can_only_start_the_existing_protected_main_workflow(self) -> None:
        relay = self.workflow["jobs"]["dispatch"]
        self.assertEqual(
            relay["if"],
            f"github.repository == '{TARGET}' && "
            "(github.event_name == 'schedule' || "
            "(github.event_name == 'push' && github.ref == 'refs/heads/develop'))",
        )
        self.assertEqual(relay["permissions"], {"actions": "write", "contents": "read"})
        self.assertNotIn("environment", relay)
        self.assertEqual(len(relay["steps"]), 1)
        self.assertEqual(relay["steps"][0]["env"], {"GH_TOKEN": "${{ github.token }}"})
        self.assertEqual(
            relay["steps"][0]["run"],
            'set -euo pipefail\n'
            'test "${GITHUB_RUN_ATTEMPT}" -eq 1\n'
            'gh workflow run promote-develop-to-main.yml \\\n'
            '  --repo "$GITHUB_REPOSITORY" \\\n'
            '  --ref main\n',
        )

    def test_reruns_are_rejected_before_credentials(self) -> None:
        first = self.job["steps"][0]
        self.assertEqual(first["name"], "Reject reruns before credential minting")
        self.assertIn('test "${GITHUB_RUN_ATTEMPT}" -eq 1', first["run"])
        self.assertEqual(self.workflow["concurrency"]["cancel-in-progress"], False)

    def test_ready_aggregate_binding_is_created_without_cumulative_review(self) -> None:
        self.assertIn("<!-- lit-protected-promotion:v2 -->", self.script)
        self.assertIn("<!-- lit-promotion-evidence-ready:${expected_base}:${expected_head} -->", self.script)
        self.assertIn('-f "body=${ready_body}"', self.script)
        self.assertNotIn("release-bot-exact-head-review.yml", self.text)
        self.assertNotIn("gh workflow run", self.script)
        self.assertNotIn("gh pr ready", self.script)
        self.assertNotIn("--draft", self.script)

    def test_stale_and_drifted_promotions_stay_fail_closed(self) -> None:
        self.assertIn('test "${count}" -le 1', self.script)
        self.assertIn(".user.id == 307565056", self.script)
        self.assertIn(".merge_base_commit.sha == $base", self.script)
        self.assertIn("Existing promotion evidence is failed, stale, or malformed.", self.script)
        self.assertIn("Protected branch drift closed the finalized stale promotion PR.", self.script)
        self.assertIn(".body == $ready_body", self.script)


if __name__ == "__main__":
    unittest.main()
