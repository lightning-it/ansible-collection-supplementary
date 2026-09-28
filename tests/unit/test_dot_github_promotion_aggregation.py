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


def promotion_run(
    *,
    run_id: int = RUN_ID,
    status: str = "completed",
    conclusion: str = "success",
    required_workflow: bool = False,
) -> dict[str, Any]:
    workflow_kind = "required_workflows" if required_workflow else "workflows"
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
        "workflow_url": (
            f"https://api.github.com/repos/{MODULE.TARGET_REPOSITORY}/actions/{workflow_kind}/{WORKFLOW_ID}"
        ),
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


def verification_environment(workflow_sha: str) -> dict[str, str]:
    return {
        "REPOSITORY": MODULE.TARGET_REPOSITORY,
        "EVENT_ACTION": "opened",
        "EVENT_BASE": BASE,
        "EVENT_HEAD": HEAD,
        "PR_NUMBER": str(PR_NUMBER),
        "GITHUB_SERVER_URL": "https://github.com",
        "WORKFLOW_REF": MODULE.SOURCE_WORKFLOW_REF,
        "WORKFLOW_SHA": workflow_sha,
    }


def base_verification_payloads(
    workflow_sha: str,
    live_pr: dict[str, Any],
) -> dict[str, Any]:
    return {
        f"repos/{MODULE.SOURCE_REPOSITORY}": {
            "full_name": MODULE.SOURCE_REPOSITORY,
            "visibility": "public",
            "archived": False,
            "disabled": False,
        },
        f"repos/{MODULE.SOURCE_REPOSITORY}/branches/main": {
            "name": "main",
            "protected": True,
            "commit": {"sha": workflow_sha},
        },
        f"repos/{MODULE.SOURCE_REPOSITORY}/compare/{workflow_sha}...{workflow_sha}": {
            "base_commit": {"sha": workflow_sha},
            "merge_base_commit": {"sha": workflow_sha},
            "status": "identical",
            "ahead_by": 0,
            "behind_by": 0,
        },
        (f"repos/{MODULE.SOURCE_REPOSITORY}/contents/{MODULE.SOURCE_WORKFLOW_PATH}?ref={workflow_sha}"): {
            "type": "file",
            "sha": "d" * 40,
        },
        (
            f"repos/{MODULE.SOURCE_REPOSITORY}/contents/"
            f"scripts/verify-dot-github-current-revision.py?ref={workflow_sha}"
        ): {"type": "file", "sha": "e" * 40},
        f"repos/{MODULE.TARGET_REPOSITORY}": {
            "full_name": MODULE.TARGET_REPOSITORY,
            "default_branch": "develop",
            "archived": False,
            "disabled": False,
        },
        f"repos/{MODULE.TARGET_REPOSITORY}/pulls/{PR_NUMBER}": live_pr,
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


class SequencedLivePrClient(MappingClient):
    """Return mutable live-PR snapshots while keeping every other fixture fixed."""

    def __init__(self, payloads: dict[str, Any], live_prs: list[dict[str, Any]]) -> None:
        super().__init__(payloads)
        self.live_prs = live_prs

    def get(self, path: str) -> Any:
        pr_path = f"repos/{MODULE.TARGET_REPOSITORY}/pulls/{PR_NUMBER}"
        if path == pr_path:
            self.paths.append(path)
            if len(self.live_prs) > 1:
                return deepcopy(self.live_prs.pop(0))
            return deepcopy(self.live_prs[0])
        return super().get(path)


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


class SequencedPromotionInventoryClient:
    """Expose a newer exact aggregate after an earlier terminal result."""

    api_url = "https://api.github.com"

    def __init__(
        self,
        inventories: list[dict[str, Any]],
        runs: dict[int, dict[str, Any]],
    ) -> None:
        self.inventories = inventories
        self.runs = runs

    def get(self, path: str) -> Any:
        if path.endswith("&filter=all&per_page=100"):
            if len(self.inventories) > 1:
                return deepcopy(self.inventories.pop(0))
            return deepcopy(self.inventories[0])
        if "/actions/runs/" in path:
            run_id = int(path.rsplit("/", 1)[1])
            return deepcopy(self.runs[run_id])
        raise AssertionError(f"unexpected path: {path}")


class PromotionShapeTests(unittest.TestCase):
    def test_classifies_only_the_release_app_develop_to_main_identity(self) -> None:
        self.assertTrue(MODULE.is_aggregated_promotion(promotion_pr()))

        wrong_author = promotion_pr()
        wrong_author["user"]["id"] += 1
        self.assertFalse(MODULE.is_aggregated_promotion(wrong_author))

        wrong_head = promotion_pr()
        wrong_head["head"]["ref"] = "feature"
        self.assertFalse(MODULE.is_aggregated_promotion(wrong_head))

    def test_rejects_a_malformed_promotion_title_without_legacy_fallback(self) -> None:
        malformed = promotion_pr()
        malformed["title"] = "chore(release): altered title"

        self.assertTrue(MODULE.is_aggregated_promotion(malformed))
        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "promotion pull request title is not exactly bound",
        ):
            MODULE.validate_aggregated_promotion_shape(malformed)

    def test_verify_rejects_malformed_promotion_before_reservation_lookup(self) -> None:
        workflow_sha = "c" * 40
        malformed = promotion_pr()
        malformed["title"] = "chore(release): altered title"
        client = MappingClient(base_verification_payloads(workflow_sha, malformed))

        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "promotion pull request title is not exactly bound",
        ):
            MODULE.verify(
                client,
                verification_environment(workflow_sha),
                attempts=1,
                sleep=lambda _: None,
            )

        self.assertFalse(any("/check-runs" in path for path in client.paths))

    def test_verify_rejects_promotion_title_drift_at_final_reread(self) -> None:
        workflow_sha = "c" * 40
        drifted = promotion_pr()
        drifted["title"] = "chore(release): altered title"
        payloads = base_verification_payloads(workflow_sha, promotion_pr())
        del payloads[f"repos/{MODULE.TARGET_REPOSITORY}/pulls/{PR_NUMBER}"]
        payloads.update(
            {
                (
                    f"repos/{MODULE.TARGET_REPOSITORY}/commits/{HEAD}/check-runs"
                    f"?check_name=Required%20current-revision%20workflow"
                    "&filter=all&per_page=100"
                ): {"total_count": 1, "check_runs": [promotion_check()]},
                f"repos/{MODULE.TARGET_REPOSITORY}/actions/runs/{RUN_ID}": promotion_run(),
                f"repos/{MODULE.TARGET_REPOSITORY}/actions/workflows/{WORKFLOW_ID}": {
                    "id": WORKFLOW_ID,
                    "path": MODULE.TARGET_VERIFIER_PATH,
                    "state": "active",
                },
                (f"repos/{MODULE.TARGET_REPOSITORY}/actions/runs/{RUN_ID}/attempts/1/jobs?per_page=100"): {
                    "total_count": 2,
                    "jobs": [
                        {
                            "id": JOB_ID,
                            "name": MODULE.TARGET_VERIFIER_NAME,
                            "head_sha": HEAD,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",
                        },
                        {
                            "id": JOB_ID - 1,
                            "name": MODULE.PROMOTION_VERIFIER_NAME,
                            "head_sha": HEAD,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",
                        },
                    ],
                },
            }
        )
        client = SequencedLivePrClient(payloads, [promotion_pr(), drifted])

        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "promotion pull request title is not exactly bound",
        ):
            MODULE.verify(
                client,
                verification_environment(workflow_sha),
                attempts=1,
                sleep=lambda _: None,
            )

        self.assertEqual(
            2,
            client.paths.count(f"repos/{MODULE.TARGET_REPOSITORY}/pulls/{PR_NUMBER}"),
        )

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
        for _check, run in checks_and_runs:
            run_id = run["id"]
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

    def test_waits_for_a_newer_result_after_an_earlier_terminal_failure(self) -> None:
        failed_check = promotion_check(run_id=100, job_id=200, conclusion="failure")
        success_check = promotion_check(run_id=101, job_id=201)
        client = SequencedPromotionInventoryClient(
            [
                self.inventory(failed_check),
                self.inventory(failed_check, success_check),
            ],
            {
                100: promotion_run(run_id=100, conclusion="failure"),
                101: promotion_run(run_id=101),
            },
        )
        sleeps: list[float] = []

        check, run, job_id = MODULE.wait_for_aggregated_promotion(
            client,
            PR_NUMBER,
            BASE,
            HEAD,
            attempts=2,
            sleep=sleeps.append,
        )

        self.assertEqual(201, check["id"])
        self.assertEqual(101, run["id"])
        self.assertEqual(201, job_id)
        self.assertEqual([10], sleeps)

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

    def test_rejects_newer_mismatched_association_instead_of_reusing_success(self) -> None:
        older_check = promotion_check(run_id=100, job_id=200)
        newer_check = promotion_check(run_id=101, job_id=201)
        newer_run = promotion_run(run_id=101)
        newer_run["pull_requests"][0]["number"] = PR_NUMBER + 1
        client = self.client_for(
            (older_check, promotion_run(run_id=100)),
            (newer_check, newer_run),
        )

        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "latest aggregated promotion association is not exactly bound",
        ):
            MODULE.wait_for_aggregated_promotion(
                client,
                PR_NUMBER,
                BASE,
                HEAD,
                attempts=1,
                sleep=lambda _: None,
            )

    def test_rejects_malformed_same_head_url_instead_of_reusing_success(self) -> None:
        older_check = promotion_check(run_id=100, job_id=200)
        newer_check = promotion_check(run_id=101, job_id=201)
        newer_check["details_url"] = f"https://github.com/{MODULE.TARGET_REPOSITORY}/checks/201"
        client = self.client_for(
            (older_check, promotion_run(run_id=100)),
            (newer_check, promotion_run(run_id=101)),
        )

        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "aggregated promotion check details URL is not exactly bound",
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
    def client(
        self,
        *,
        include_aggregate: bool = True,
        required_workflow: bool = False,
    ) -> MappingClient:
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
        workflow_kind = "required_workflows" if required_workflow else "workflows"
        return MappingClient(
            {
                f"repos/{MODULE.TARGET_REPOSITORY}/actions/{workflow_kind}/{WORKFLOW_ID}": {
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

    def test_accepts_the_exact_required_workflow_endpoint(self) -> None:
        MODULE.validate_aggregated_promotion(
            self.client(required_workflow=True),
            (
                promotion_check(),
                promotion_run(required_workflow=True),
                JOB_ID,
            ),
            promotion_pr(),
            PR_NUMBER,
            BASE,
            HEAD,
            "https://github.com",
        )

    def test_rejects_a_drifted_complete_evidence_tuple(self) -> None:
        original = (promotion_check(), promotion_run(), JOB_ID)
        drifted_check = promotion_check()
        drifted_check["conclusion"] = "failure"
        drifted = (drifted_check, promotion_run(), JOB_ID)

        self.assertNotEqual(original, drifted)
        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "promotion check conclusion is not exactly bound",
        ):
            MODULE.validate_aggregated_promotion(
                self.client(),
                drifted,
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
