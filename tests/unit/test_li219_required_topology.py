"""Execute the shipped offline selector; never call GitHub or request a rerun."""

import copy
import json
import os
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = [ROOT / ".github/workflows/current-revision-rerun.yml"]
ROUTE = "Route protected current-revision verification"
LEGACY = "Legacy protected current-revision verifier"
REQUIRED = "Required current-revision workflow"
S0_NAMES = (
    "Reserve protected S0 feature-to-main verification",
    "Verify protected S0 feature-to-main input",
    "Finalize the protected S0 feature-to-main result",
)
AUTHORIZATION = "Authorize exact Supplementary catch-up v5 successor"
PROMOTION = "Verify aggregated develop-to-main promotion evidence"


def job(name, ident, conclusion="failure", runner=True):
    return {
        "id": ident,
        "name": name,
        "run_id": 100,
        "head_sha": "4" * 40,
        "runner_id": 100 if runner else None,
        "run_attempt": 1,
        "steps": [{"name": "protected verification"}] if runner else [],
        "status": "completed",
        "conclusion": conclusion,
    }


def routed_jobs():
    return [
        job(ROUTE, 10, "success"),
        job(LEGACY, 20),
        job(REQUIRED, 30),
        *[job(name, 40 + index, "skipped", False) for index, name in enumerate(S0_NAMES)],
    ]


class RequiredWorkflowTopologyTests(unittest.TestCase):
    def select(self, jobs, expected=None, totals=None, reservations=()):
        # Extract the real validation/selection block, ending before the first
        # mutation-boundary API revalidation. No duplicated selector algorithm.
        for path in WORKFLOWS:
            with self.subTest(workflow=str(path.relative_to(ROOT))):
                text = path.read_text(encoding="utf-8")
                section = text.split(
                    "          # Validate only the converged attempt-one inventory.",
                    1,
                )[1]
                section = section[section.index("\n          jq -e \\\n") :]
                section = section.split("          revalidate_pr_metadata", 1)[0]
                self.assertNotIn("gh api", section)
                script = "set -euo pipefail\n" + textwrap.dedent(section)
                script += '\nprintf "%s\\n" "${required_job_id}"\n'
                # Multiple pages exercise flattened complete inventories.
                pages = [
                    {"total_count": len(jobs), "jobs": jobs[:2]},
                    {"total_count": len(jobs), "jobs": jobs[2:]},
                ]
                if totals is not None:
                    for page, total in zip(pages, totals, strict=True):
                        page["total_count"] = total
                result = subprocess.run(  # noqa: S603 -- fixed local selector with offline JSON fixtures.
                    [shutil.which("bash") or "/bin/bash", "-c", script],
                    env={
                        **os.environ,
                        "attempt_one_jobs_pages": json.dumps(pages),
                        "matching_reservations": json.dumps(reservations),
                        "run_id": "100",
                        "EXPECTED_HEAD": "4" * 40,
                    },
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                if expected is None:
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertEqual(result.stdout, "")
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), str(expected))

    def test_original_single_verifier_remains_supported(self):
        self.select([job(REQUIRED, 30)], 30)

    def test_incomplete_or_inconsistent_page_totals_fail(self):
        for totals in ((7, 7), (6, 7), (7, 6), (5, 5), (-1, -1), (6.5, 6.5)):
            with self.subTest(totals=totals):
                self.select(routed_jobs(), totals=totals)
        self.select([job(REQUIRED, 30)], totals=(2, 2))

    def test_malformed_or_mismatched_job_inventory_fails(self):
        cases = []
        for field in ("run_id", "head_sha", "run_attempt", "status", "steps"):
            malformed = routed_jobs()
            malformed[0].pop(field)
            cases.append((f"missing-{field}", malformed))

        for field, value in (
            ("run_id", 101),
            ("head_sha", "5" * 40),
            ("run_attempt", 2),
            ("status", "in_progress"),
            ("steps", {"name": "not-an-array"}),
        ):
            malformed = routed_jobs()
            malformed[0][field] = value
            cases.append((f"mismatched-{field}", malformed))

        duplicate = routed_jobs()
        duplicate[1]["id"] = duplicate[0]["id"]
        cases.append(("duplicate-job-id", duplicate))

        fractional = routed_jobs()
        fractional[0]["id"] = 10.5
        cases.append(("fractional-job-id", fractional))

        for name, jobs in cases:
            with self.subTest(case=name):
                self.select(jobs)

    def test_routed_topology_selects_verifier_not_aggregator(self):
        self.select(routed_jobs(), 20)

    def test_known_optional_checks_and_authorization_are_not_targets(self):
        optional = [
            job(AUTHORIZATION, 50, "skipped", False),
            job("Current revision review", 60, "success", False),
            job("Protected current-revision verifier", 70, "success", False),
        ]
        self.select(routed_jobs() + optional, 20)
        self.select([job(REQUIRED, 30)] + optional, 30)

    def test_skipped_promotion_job_is_accepted_in_both_topologies(self):
        promotion = job(PROMOTION, 80, "skipped", False)
        self.select(routed_jobs() + [promotion], 20)
        self.select([job(REQUIRED, 30), promotion], 30)

    def test_malformed_or_duplicate_promotion_jobs_fail(self):
        for changes in (
            {"conclusion": "success"},
            {"conclusion": "failure"},
            {"runner_id": 100},
            {"steps": [{"name": "executed"}]},
        ):
            with self.subTest(changes=changes):
                promotion = job(PROMOTION, 80, "skipped", False)
                promotion.update(changes)
                self.select(routed_jobs() + [promotion])
                self.select([job(REQUIRED, 30), promotion])
        first = job(PROMOTION, 80, "skipped", False)
        second = job(PROMOTION, 81, "skipped", False)
        self.select(routed_jobs() + [first, second])
        self.select([job(REQUIRED, 30), first, second])

    def test_synthetic_evidence_must_be_completed_success(self):
        for name in ("Current revision review", "Protected current-revision verifier"):
            for changes in (
                {"status": "queued", "conclusion": ""},
                {"status": "in_progress", "conclusion": ""},
                {"conclusion": "failure"},
                {"conclusion": "cancelled"},
                {"conclusion": "skipped"},
            ):
                with self.subTest(name=name, changes=changes):
                    evidence = job(name, 60, "success", False)
                    evidence.update(changes)
                    self.select(routed_jobs() + [evidence])
                    self.select([job(REQUIRED, 30), evidence])

    def test_exact_failed_reservation_is_not_success_evidence_or_rerun_target(self):
        # PR465: the synchronize verifier failed while the PR was Draft. Its
        # own failed reservation remained in attempt one's jobs after Ready
        # published the one successful current-head review (nine jobs total).
        failed = job("Protected current-revision verifier", 70, "failure", False)
        failed.update(run_id=100, head_sha="4" * 40)
        neutral = job("Current revision review", 60, "success", False)
        promotion = job(PROMOTION, 80, "skipped", False)
        self.select(
            routed_jobs() + [failed, neutral, promotion],
            20,
            reservations=[failed],
        )
        self.select([job(REQUIRED, 30), failed, neutral], 30, reservations=[failed])

    def test_failed_reservation_requires_exact_independently_bound_identity(self):
        failed = job("Protected current-revision verifier", 70, "failure", False)
        failed.update(run_id=100, head_sha="4" * 40)
        for changes in (
            {"id": 71},
            {"run_id": 101},
            {"head_sha": "5" * 40},
            {"name": "Current revision review"},
            {"name": "Unknown check"},
            {"run_attempt": 2},
            {"runner_id": 100},
            {"steps": [{"name": "executed"}]},
            {"status": "in_progress"},
            {"conclusion": "cancelled"},
        ):
            with self.subTest(changes=changes):
                changed = {**failed, **changes}
                self.select(routed_jobs() + [changed], reservations=[failed])
        for reservations in (
            [],
            [failed, failed],
            [{**failed, "id": 71}],
            [{**failed, "status": "in_progress"}],
            [{**failed, "conclusion": "success"}],
            [{**failed, "head_sha": "5" * 40}],
        ):
            with self.subTest(reservations=reservations):
                self.select(routed_jobs() + [failed], reservations=reservations)
        self.select(routed_jobs() + [failed, failed], reservations=[failed])

    def test_missing_or_extra_topology_jobs_fail(self):
        jobs = routed_jobs()
        for index in range(len(jobs)):
            with self.subTest(missing=jobs[index]["name"]):
                self.select(jobs[:index] + jobs[index + 1 :])
        self.select(jobs + [job("Unexpected runner", 90)])
        self.select(jobs + [job("Unexpected skipped job", 90, "skipped", False)])
        self.select([job(REQUIRED, 30), job(LEGACY, 20)])

    def test_all_s0_jobs_must_be_skipped_and_runnerless(self):
        for index in range(3, 6):
            for changes in (
                {"conclusion": "success"},
                {"conclusion": "failure"},
                {"runner_id": 100},
                {"steps": [{"name": "executed"}]},
            ):
                with self.subTest(index=index, changes=changes):
                    jobs = routed_jobs()
                    jobs[index].update(changes)
                    self.select(jobs)

    def test_runner_results_and_execution_are_exact(self):
        for index in range(3):
            for changes in (
                {"conclusion": "cancelled"},
                {"conclusion": "skipped"},
                {"conclusion": "failure" if index == 0 else "success"},
                {"runner_id": None},
                {"steps": []},
            ):
                with self.subTest(index=index, changes=changes):
                    jobs = routed_jobs()
                    jobs[index].update(changes)
                    self.select(jobs)

    def test_duplicate_names_or_ids_fail(self):
        jobs = routed_jobs()
        self.select(jobs + [copy.deepcopy(jobs[0])])
        jobs[1]["id"] = jobs[0]["id"]
        self.select(jobs)
        evidence = job("Current revision review", 60, "success", False)
        duplicate = {**evidence, "id": 61}
        self.select(routed_jobs() + [evidence, duplicate])

    def test_attempt_two_or_unfinished_jobs_fail(self):
        for index in range(6):
            for changes in ({"run_attempt": 2}, {"status": "in_progress"}):
                jobs = routed_jobs()
                jobs[index].update(changes)
                self.select(jobs)

    def test_malformed_jobs_fail_before_selection(self):
        for field in ("id", "name", "runner_id", "steps", "status", "run_attempt"):
            jobs = routed_jobs()
            del jobs[1][field]
            self.select(jobs)
        for changes in ({"id": 0}, {"runner_id": 0}, {"steps": None}):
            jobs = routed_jobs()
            jobs[1].update(changes)
            self.select(jobs)

    def test_non_skipped_authorization_fails(self):
        self.select(routed_jobs() + [job(AUTHORIZATION, 50, "success", False)])
        self.select(routed_jobs() + [job(AUTHORIZATION, 50, "success")])


if __name__ == "__main__":
    unittest.main()
