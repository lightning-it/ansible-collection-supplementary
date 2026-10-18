"""Bind the repo-local LI-139 adoption to the already reviewed central promoter.

Source: lightning-it/shared-assets-lit@b3c96a1e8164caaa7313d05998677a883f00e2e1
Path: .github/workflows/promote-develop-to-main.yml
The canonical mutation code is unchanged. Rendering retains the repo's
protected-main relay and approval environment, plus its exact identity binding.
A repository-local pre-mutation guard authenticates release-state transitions.
Its explicitly checked read-only normal proof adapter adds no mutation authority;
normalization below retains the original reviewed donor mutation hash.
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
        guard_start = self.text.index("          # LI-139 release-state guard:start\n")
        guard_end = self.text.index("          # LI-139 release-state guard:end\n") + len(
            "          # LI-139 release-state guard:end\n"
        )
        rendered = self.text[:guard_start] + self.text[guard_end:]
        for kind, indentation in (("permissions", "    "), ("tools", "      "), ("bindings", "          ")):
            start = f"{indentation}# LI-344 readonly normal proof {kind}:start\n"
            end = f"{indentation}# LI-344 readonly normal proof {kind}:end\n"
            self.assertEqual(rendered.count(start), 1)
            self.assertEqual(rendered.count(end), 1)
            first = rendered.index(start)
            last = rendered.index(end, first) + len(end)
            block = yaml.safe_load(rendered[first + len(start) : last - len(end)])
            if kind == "permissions":
                self.assertEqual(block, {"permissions": {"contents": "read", "actions": "read"}})
            elif kind == "bindings":
                self.assertEqual(
                    block, {"REPOSITORY_ID": "${{ github.repository_id }}", "NATIVE_READ_TOKEN": "${{ github.token }}"}
                )
            else:
                self.assertEqual(
                    block,
                    [
                        {
                            "name": "Checkout adopted native normal proof source",
                            "uses": "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
                            "with": {
                                "repository": "lightning-it/.github",
                                "ref": "bb1a5df9f54c5f98547048297e7e367cc382543e",
                                "path": ".native-normal-control",
                                "fetch-depth": 0,
                                "persist-credentials": False,
                            },
                        },
                        {
                            "name": "Set up normal receipt proof parser",
                            "uses": "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1",
                            "with": {"python-version": "3.14"},
                        },
                        {
                            "name": "Install pinned normal receipt parser",
                            "run": "python -m pip install --disable-pip-version-check --no-input PyYAML==6.0.3",
                        },
                    ],
                )
            if kind == "tools":
                self.assertEqual(rendered[last], "\n")
                last += 1
            rendered = rendered[:first] + rendered[last:]
        relay_start = rendered.index("  dispatch:\n")
        relay_end = rendered.index("  promote:\n", relay_start)
        canonical = (
            (rendered[:relay_start] + rendered[relay_end:])
            .replace(
                "# Repository-local adoption from lightning-it/shared-assets-lit.",
                "# Managed by lightning-it/shared-assets-lit.",
                1,
            )
            .replace(MAIN_CONDITION, "    if: github.repository == 'lightning-it/shared-assets-lit'\n", 1)
            .replace("    environment: ansible-collection-release-prepare\n", "", 1)
        )
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
        mint = next(step for step in self.job["steps"] if step.get("id") == "release-app")
        self.assertEqual(mint["uses"], "actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1")
        self.assertEqual(mint["with"]["repositories"], "${{ github.event.repository.name }}")
        self.assertEqual(mint["with"]["permission-contents"], "read")
        self.assertEqual(mint["with"]["permission-pull-requests"], "write")
        self.assertNotIn("permission-actions", mint["with"])
        self.assertEqual(self.job["permissions"], {"contents": "read", "actions": "read"})
        source = next(
            step for step in self.job["steps"] if step.get("name") == "Checkout adopted native normal proof source"
        )
        self.assertEqual(source["with"]["repository"], "lightning-it/.github")
        self.assertEqual(source["with"]["ref"], "bb1a5df9f54c5f98547048297e7e367cc382543e")
        self.assertFalse(source["with"]["persist-credentials"])
        bindings = self.job["steps"][-1]["env"]
        self.assertEqual(bindings["NATIVE_READ_TOKEN"], "${{ github.token }}")
        self.assertEqual(bindings["REPOSITORY_ID"], "${{ github.repository_id }}")

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
            "set -euo pipefail\n"
            'test "${GITHUB_RUN_ATTEMPT}" -eq 1\n'
            "gh workflow run promote-develop-to-main.yml \\\n"
            '  --repo "$GITHUB_REPOSITORY" \\\n'
            "  --ref main\n",
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
