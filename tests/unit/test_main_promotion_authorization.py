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


class NormalPromotionApprovalTests(unittest.TestCase):
    def authorization(self):
        return AUTHORIZATION.Authorization(
            mode="normal",
            environment=AUTHORIZATION.NORMAL_ENVIRONMENT,
            head_sha="a" * 40,
            head_ref="develop",
        )

    def environment(self, *, prevent_self_review: bool = False, reviewers: list[dict] | None = None):
        roster = reviewers if reviewers is not None else [
            {"type": "User", "reviewer": {"id": user_id, "login": login}}
            for user_id, login in AUTHORIZATION.NORMAL_PROMOTION_APPROVERS.items()
        ]
        return {
            "name": AUTHORIZATION.NORMAL_ENVIRONMENT,
            "can_admins_bypass": False,
            "protection_rules": [
                {"type": "required_reviewers", "prevent_self_review": prevent_self_review, "reviewers": roster}
            ],
        }

    def test_accepts_the_exact_small_team_self_approval_roster(self):
        AUTHORIZATION.validate_environment(self.environment(), self.authorization())

    def test_rejects_a_self_review_prohibition(self):
        with self.assertRaisesRegex(AUTHORIZATION.AuthorizationError, "allow small-team self-review"):
            AUTHORIZATION.validate_environment(self.environment(prevent_self_review=True), self.authorization())

    def test_rejects_a_changed_reviewer_roster(self):
        reviewers = [
            {"type": "User", "reviewer": {"id": user_id, "login": login}}
            for user_id, login in AUTHORIZATION.NORMAL_PROMOTION_APPROVERS.items()
        ]
        reviewers[-1] = {"type": "User", "reviewer": {"id": 1, "login": "unexpected"}}
        with self.assertRaisesRegex(AUTHORIZATION.AuthorizationError, "exact small-team roster"):
            AUTHORIZATION.validate_environment(self.environment(reviewers=reviewers), self.authorization())


if __name__ == "__main__":
    unittest.main()
