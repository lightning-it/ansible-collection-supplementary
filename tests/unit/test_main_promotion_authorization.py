"""Regression tests for the protected normal-promotion approval roster."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "main-promotion-authorization.py"
sys.path.insert(0, str(SCRIPT.parent))


def load_module():
    spec = importlib.util.spec_from_file_location("main_promotion_authorization_tested", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


AUTHORIZATION = load_module()
EXPECTED_RELEASE_TEAM_ID = 15545798


class NormalPromotionApprovalTests(unittest.TestCase):
    def authorization(self):
        return AUTHORIZATION.Authorization(
            mode="normal",
            environment=AUTHORIZATION.NORMAL_ENVIRONMENT,
            head_sha="a" * 40,
            head_ref="develop",
        )

    def environment(self, *, prevent_self_review: bool = False, reviewers: list[dict] | None = None):
        roster = (
            reviewers
            if reviewers is not None
            else [{"type": "BusinessTeam", "reviewer": {"id": EXPECTED_RELEASE_TEAM_ID}}]
        )
        return {
            "name": AUTHORIZATION.NORMAL_ENVIRONMENT,
            "can_admins_bypass": False,
            "protection_rules": [
                {"type": "required_reviewers", "prevent_self_review": prevent_self_review, "reviewers": roster}
            ],
        }

    def test_accepts_the_release_team_small_team_self_approval_contract(self):
        self.assertEqual(AUTHORIZATION.RELEASE_TEAM_ID, EXPECTED_RELEASE_TEAM_ID)
        AUTHORIZATION.validate_environment(self.environment(), self.authorization())

    def test_rejects_a_self_review_prohibition(self):
        with self.assertRaisesRegex(AUTHORIZATION.AuthorizationError, "allow small-team self-review"):
            AUTHORIZATION.validate_environment(self.environment(prevent_self_review=True), self.authorization())

    def test_rejects_a_different_release_team(self):
        reviewers = [{"type": "BusinessTeam", "reviewer": {"id": 1}}]
        with self.assertRaisesRegex(AUTHORIZATION.AuthorizationError, "release team"):
            AUTHORIZATION.validate_environment(self.environment(reviewers=reviewers), self.authorization())


if __name__ == "__main__":
    unittest.main()
