"""Regression tests for native develop-to-main promotion aggregation."""

from __future__ import annotations

import importlib.util
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify-dot-github-current-revision.py"
SPEC = importlib.util.spec_from_file_location("dot_github_verifier", SCRIPT)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - import contract
    raise RuntimeError("Unable to load the dot-github verifier")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

BASE = "a" * 40
HEAD = "b" * 40
PR_NUMBER = 640
RUN_ID = 1234
JOB_ID = 5678
WORKFLOW_ID = 9012


def promotion_pr() -> dict[str, Any]:
    return {
        "number": PR_NUMBER,
        "state": "open",
        "draft": False,
        "title": MODULE.PROMOTION_TITLE,
        "user": {
            "login": MODULE.RELEASE_APP_LOGIN,
            "id": MODULE.RELEASE_APP_ID,
            "type": "Bot",
        },
        "base": {
            "ref": "main",
            "sha": BASE,
            "repo": {"full_name": MODULE.TARGET_REPOSITORY},
        },
        "head": {
            "ref": "develop",
            "sha": HEAD,
            "repo": {"full_name": MODULE.TARGET_REPOSITORY},
        },
    }


def association() -> dict[str, Any]:
    repository_url = f"https://api.github.com/repos/{MODULE.TARGET_REPOSITORY}"
    return {
        "number": PR_NUMBER,
        "base": {
            "ref": "main",
            "sha": BASE,
            "repo": {"name": ".github", "url": repository_url},
        },
        "head": {
            "ref": "develop",
            "sha": HEAD,
            "repo": {"name": ".github", "url": repository_url},
        },
    }


def promotion_run(*, run_id: int = RUN_ID, status: str = "completed", conclusion: str = "success") -> dict[str, Any]:
    return {
        "id": run_id,
        "event": "pull_request_target",
        "path": MODULE.TARGET_VERIFIER_PATH,
        "status": status,
        "conclusion": conclusion,
        "head_sha": HEAD,
        "head_branch": "develop",
        "run_attempt": 1,
        "actor": {"login": MODULE.RELEASE_APP_LOGIN},
        "triggering_actor": {"login": MODULE.RELEASE_APP_LOGIN},
        "display_title": f"Protected current revision PR #{PR_NUMBER} edited {HEAD}",
        "html_url": f"https://github.com/{MODULE.TARGET_REPOSITORY}/actions/runs/{run_id}",
        "workflow_id": WORKFLOW_ID,
        "workflow_url": (f"https://api.github.com/repos/{MODULE.TARGET_REPOSITORY}/actions/workflows/{WORKFLOW_ID}"),
        "pull_requests": [association()],
    }


def promotion_check(
    *,
    run_id: int = RUN_ID,
    job_id: int = JOB_ID,
    status: str = "completed",
    conclusion: str = "success",
) -> dict[str, Any]:
    return {
        "id": job_id,
        "name": MODULE.TARGET_VERIFIER_NAME,
        "head_sha": HEAD,
        "status": status,
        "conclusion": conclusion,
        "details_url": (f"https://github.com/{MODULE.TARGET_REPOSITORY}/actions/runs/{run_id}/job/{job_id}"),
        "external_id": "provider-owned",
        "app": {"id": 15368, "slug": "github-actions"},
    }


class MappingClient:
    """Serve immutable REST fixtures by exact path."""

    api_url = "https://api.github.com"

    def __init__(self, payloads: dict[str, Any]) -> None:
        self.payloads = payloads
        self.paths: list[str] = []

    def get(self, path: str) -> Any:
        self.paths.append(path)
        return deepcopy(self.payloads[path])


class SequencedPromotionClient:
    """Keep the check stable while its exact producing run converges."""

    api_url = "https://api.github.com"

    def __init__(self, check: dict[str, Any], runs: list[dict[str, Any]]) -> None:
        self.check = check
        self.runs = runs

    def get(self, path: str) -> Any:
        if path.endswith("&filter=all&per_page=100"):
            return {"total_count": 1, "check_runs": [deepcopy(self.check)]}
        if "/actions/runs/" in path:
            if len(self.runs) > 1:
                return deepcopy(self.runs.pop(0))
            return deepcopy(self.runs[0])
        raise AssertionError(f"unexpected path: {path}")


class PromotionShapeTests(unittest.TestCase):
    def test_recognizes_only_the_release_app_develop_to_main_shape(self) -> None:
        self.assertTrue(MODULE.is_aggregated_promotion(promotion_pr()))

        wrong_author = promotion_pr()
        wrong_author["user"]["id"] += 1
        self.assertFalse(MODULE.is_aggregated_promotion(wrong_author))

        wrong_head = promotion_pr()
        wrong_head["head"]["ref"] = "feature"
        self.assertFalse(MODULE.is_aggregated_promotion(wrong_head))

    def test_requires_one_exact_pull_request_association(self) -> None:
        run = promotion_run()
        self.assertTrue(MODULE.exact_promotion_run_association(run, PR_NUMBER, BASE, HEAD))

        run["pull_requests"].append(association())
        self.assertFalse(MODULE.exact_promotion_run_association(run, PR_NUMBER, BASE, HEAD))


class PromotionSelectionTests(unittest.TestCase):
    @staticmethod
    def inventory(*checks: dict[str, Any]) -> dict[str, Any]:
        return {"total_count": len(checks), "check_runs": list(checks)}

    def client_for(self, *checks_and_runs: tuple[dict[str, Any], dict[str, Any]]) -> MappingClient:
        checks = [item[0] for item in checks_and_runs]
        payloads: dict[str, Any] = {
            (
                f"repos/{MODULE.TARGET_REPOSITORY}/commits/{HEAD}/check-runs"
                f"?check_name=Required%20current-revision%20workflow"
                "&filter=all&per_page=100"
            ): self.inventory(*checks)
        }
        for check, run in checks_and_runs:
            run_id = check["details_url"].split("/runs/")[1].split("/job/")[0]
            payloads[f"repos/{MODULE.TARGET_REPOSITORY}/actions/runs/{run_id}"] = run
        return MappingClient(payloads)

    def test_selects_the_newest_exact_successful_result(self) -> None:
        older_check = promotion_check(run_id=100, job_id=200)
        newer_check = promotion_check(run_id=101, job_id=201)
        client = self.client_for(
            (older_check, promotion_run(run_id=100)),
            (newer_check, promotion_run(run_id=101)),
        )

        check, run, job_id = MODULE.wait_for_aggregated_promotion(
            client,
            PR_NUMBER,
            BASE,
            HEAD,
            attempts=1,
            sleep=lambda _: None,
        )

        self.assertEqual(201, check["id"])
        self.assertEqual(101, run["id"])
        self.assertEqual(201, job_id)

    def test_rejects_a_newer_failed_result_instead_of_reusing_success(self) -> None:
        older_check = promotion_check(run_id=100, job_id=200)
        newer_check = promotion_check(run_id=101, job_id=201, conclusion="failure")
        client = self.client_for(
            (older_check, promotion_run(run_id=100)),
            (
                newer_check,
                promotion_run(run_id=101, conclusion="failure"),
            ),
        )

        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "latest aggregated promotion evidence failed",
        ):
            MODULE.wait_for_aggregated_promotion(
                client,
                PR_NUMBER,
                BASE,
                HEAD,
                attempts=1,
                sleep=lambda _: None,
            )

    def test_waits_when_the_successful_check_precedes_run_completion(self) -> None:
        check = promotion_check()
        client = SequencedPromotionClient(
            check,
            [
                promotion_run(status="in_progress", conclusion=""),
                promotion_run(),
            ],
        )
        sleeps: list[float] = []

        result = MODULE.wait_for_aggregated_promotion(
            client,
            PR_NUMBER,
            BASE,
            HEAD,
            attempts=2,
            sleep=sleeps.append,
        )

        self.assertEqual(JOB_ID, result[0]["id"])
        self.assertEqual([10], sleeps)

    def test_ignores_a_successful_run_associated_with_another_pr(self) -> None:
        check = promotion_check()
        run = promotion_run()
        run["pull_requests"][0]["number"] = PR_NUMBER + 1
        client = self.client_for((check, run))

        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "aggregated promotion evidence did not become successful",
        ):
            MODULE.wait_for_aggregated_promotion(
                client,
                PR_NUMBER,
                BASE,
                HEAD,
                attempts=1,
                sleep=lambda _: None,
            )


class PromotionValidationTests(unittest.TestCase):
    def client(self, *, include_aggregate: bool = True) -> MappingClient:
        jobs = [
            {
                "id": JOB_ID,
                "name": MODULE.TARGET_VERIFIER_NAME,
                "head_sha": HEAD,
                "run_attempt": 1,
                "status": "completed",
                "conclusion": "success",
            }
        ]
        if include_aggregate:
            jobs.append(
                {
                    "id": JOB_ID - 1,
                    "name": MODULE.PROMOTION_VERIFIER_NAME,
                    "head_sha": HEAD,
                    "run_attempt": 1,
                    "status": "completed",
                    "conclusion": "success",
                }
            )
        return MappingClient(
            {
                f"repos/{MODULE.TARGET_REPOSITORY}/actions/workflows/{WORKFLOW_ID}": {
                    "id": WORKFLOW_ID,
                    "path": MODULE.TARGET_VERIFIER_PATH,
                    "state": "active",
                },
                (f"repos/{MODULE.TARGET_REPOSITORY}/actions/runs/{RUN_ID}/attempts/1/jobs?per_page=100"): {
                    "total_count": len(jobs),
                    "jobs": jobs,
                },
            }
        )

    def test_binds_the_exact_workflow_aggregate_and_final_job(self) -> None:
        MODULE.validate_aggregated_promotion(
            self.client(),
            (promotion_check(), promotion_run(), JOB_ID),
            promotion_pr(),
            PR_NUMBER,
            BASE,
            HEAD,
            "https://github.com",
        )

    def test_rejects_success_without_the_aggregate_job(self) -> None:
        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "promotion aggregate job is missing or ambiguous",
        ):
            MODULE.validate_aggregated_promotion(
                self.client(include_aggregate=False),
                (promotion_check(), promotion_run(), JOB_ID),
                promotion_pr(),
                PR_NUMBER,
                BASE,
                HEAD,
                "https://github.com",
            )


if __name__ == "__main__":
    unittest.main()
