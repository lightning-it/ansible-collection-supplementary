"""Adversarial completeness checks for the read-only promotion run inventory."""

from __future__ import annotations

import unittest

from scripts.promotion_waiter_inventory import (
    IncompleteInventory,
    collect_waiting_jobs,
    collect_waiting_runs,
)

WORKFLOW_ID = 298614219


def run(number: int) -> dict:
    return {
        "id": number,
        "workflow_id": WORKFLOW_ID,
        "status": "waiting",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": f"{number:040x}",
        "created_at": "2026-10-09T00:00:00Z",
        "updated_at": "2026-10-09T00:00:01Z",
        "run_attempt": 1,
        "actor": {"login": "github-actions[bot]"},
        "pull_requests": [],
    }


def pages(*batches: list[dict], total: int | None = None):
    count = sum(len(batch) for batch in batches) if total is None else total
    return lambda page: {"total_count": count, "workflow_runs": batches[page - 1]}


def job(number: int, run_id: int, *, head_sha: str | None = None) -> dict:
    return {
        "id": number,
        "run_id": run_id,
        "run_attempt": 1,
        "head_sha": head_sha or f"{run_id:040x}",
        "name": "Open develop-to-main promotion PR",
        "status": "waiting",
        "conclusion": None,
        "steps": [],
    }


class PromotionWaiterInventoryTests(unittest.TestCase):
    def test_complete_multi_page_inventory_is_unclassified(self) -> None:
        batch1 = [run(index) for index in range(1, 101)]
        batch2 = [run(101), run(102)]
        result = collect_waiting_runs(pages(batch1, batch2), WORKFLOW_ID)
        self.assertEqual(result["total_count"], 102)
        self.assertEqual(result["page_count"], 2)
        self.assertEqual(len(result["runs"]), 102)
        self.assertEqual({entry["disposition"] for entry in result["runs"]}, {"unclassified"})

    def test_missing_page_and_duplicate_id_fail_closed(self) -> None:
        batch1 = [run(index) for index in range(1, 101)]
        for second in ([], [run(100)]):
            with self.subTest(second=second), self.assertRaises(IncompleteInventory):
                collect_waiting_runs(pages(batch1, second, total=101), WORKFLOW_ID)

    def test_changed_total_or_first_page_fails_closed(self) -> None:
        calls = 0

        def changed(page: int) -> dict:
            nonlocal calls
            calls += 1
            if calls == 2:
                return {"total_count": 2, "workflow_runs": [run(2)]}
            return {"total_count": 1, "workflow_runs": [run(1)]}

        with self.assertRaises(IncompleteInventory):
            collect_waiting_runs(changed, WORKFLOW_ID)

        def changed_first_page(page: int) -> dict:
            nonlocal calls
            calls += 1
            return {"total_count": 1, "workflow_runs": [run(1 if calls == 4 else 2)]}

        with self.assertRaises(IncompleteInventory):
            collect_waiting_runs(changed_first_page, WORKFLOW_ID)

    def test_middle_page_change_with_stable_total_fails_closed(self) -> None:
        calls = 0

        def changed_middle(page: int) -> dict:
            nonlocal calls
            calls += 1
            if page == 1:
                return {"total_count": 101, "workflow_runs": [run(i) for i in range(1, 101)]}
            return {"total_count": 101, "workflow_runs": [run(101 if calls == 2 else 102)]}

        with self.assertRaises(IncompleteInventory):
            collect_waiting_runs(changed_middle, WORKFLOW_ID)

    def test_same_run_id_with_changed_attempt_fails_closed(self) -> None:
        calls = 0

        def changed_attempt(_page: int) -> dict:
            nonlocal calls
            calls += 1
            value = run(1)
            if calls == 2:
                value["run_attempt"] = 2
            return {"total_count": 1, "workflow_runs": [value]}

        with self.assertRaises(IncompleteInventory):
            collect_waiting_runs(changed_attempt, WORKFLOW_ID)

    def test_missing_or_nonpositive_run_attempt_fails_closed_without_jobs(self) -> None:
        for attempt in (None, 0, -1, "1", True):
            with self.subTest(attempt=attempt):
                value = run(1)
                value["run_attempt"] = attempt
                with self.assertRaises(IncompleteInventory):
                    collect_waiting_runs(pages([value]), WORKFLOW_ID)

    def test_malformed_or_naive_external_timestamp_fails_closed(self) -> None:
        for field in ("created_at", "updated_at"):
            for timestamp in (
                None,
                "",
                "yesterday",
                "2026-10-09T00:00:00",
                "2026-13-09T00:00:00Z",
                "2026-10-09T00:00:00+99:00",
            ):
                with self.subTest(field=field, timestamp=timestamp):
                    value = run(1)
                    value[field] = timestamp
                    with self.assertRaises(IncompleteInventory):
                        collect_waiting_runs(pages([value]), WORKFLOW_ID)
        value = run(1)
        value["updated_at"] = "2026-10-08T23:59:59Z"
        with self.assertRaises(IncompleteInventory):
            collect_waiting_runs(pages([value]), WORKFLOW_ID)

    def test_foreign_workflow_and_missing_identity_fail_closed(self) -> None:
        foreign = run(1)
        foreign["workflow_id"] = WORKFLOW_ID + 1
        with self.assertRaises(IncompleteInventory):
            collect_waiting_runs(pages([foreign]), WORKFLOW_ID)
        missing_pr_inventory = run(1)
        del missing_pr_inventory["pull_requests"]
        with self.assertRaises(IncompleteInventory):
            collect_waiting_runs(pages([missing_pr_inventory]), WORKFLOW_ID)

    def test_invalid_or_duplicate_pr_associations_fail_closed(self) -> None:
        for associations in ([{"number": 0}], [{"number": -2}], [{"number": 7}, {"number": 7}]):
            with self.subTest(associations=associations):
                value = run(1)
                value["pull_requests"] = associations
                with self.assertRaises(IncompleteInventory):
                    collect_waiting_runs(pages([value]), WORKFLOW_ID)

    def test_filtered_api_limit_is_not_treated_as_complete(self) -> None:
        with self.assertRaises(IncompleteInventory):
            collect_waiting_runs(lambda _: {"total_count": 1000, "workflow_runs": []}, WORKFLOW_ID)

    def test_complete_job_pages_bind_each_waiting_run_without_disposition(self) -> None:
        inventory = collect_waiting_runs(pages([run(1), run(2)]), WORKFLOW_ID)

        def fetch_jobs(run_id: int, page: int) -> dict:
            self.assertEqual(page, 1)
            return {"total_count": 1, "jobs": [job(100 + run_id, run_id)]}

        result = collect_waiting_jobs(inventory, fetch_jobs)
        self.assertEqual([entry["run_id"] for entry in result], [1, 2])
        self.assertEqual([entry["jobs"][0]["step_count"] for entry in result], [0, 0])
        self.assertEqual({entry["disposition"] for entry in inventory["runs"]}, {"unclassified"})

    def test_requested_job_status_is_inventoryable_without_disposition(self) -> None:
        inventory = collect_waiting_runs(pages([run(1)]), WORKFLOW_ID)
        requested = job(101, 1)
        requested["status"] = "requested"
        result = collect_waiting_jobs(
            inventory,
            lambda _run_id, _page: {"total_count": 1, "jobs": [requested]},
        )
        self.assertEqual(result[0]["jobs"][0]["status"], "requested")
        self.assertEqual(inventory["runs"][0]["disposition"], "unclassified")

    def test_foreign_or_duplicate_job_fails_closed(self) -> None:
        inventory = collect_waiting_runs(pages([run(1), run(2)]), WORKFLOW_ID)

        with self.assertRaises(IncompleteInventory):
            collect_waiting_jobs(
                inventory,
                lambda run_id, _: {"total_count": 1, "jobs": [job(101, run_id)]},
            )
        with self.assertRaises(IncompleteInventory):
            collect_waiting_jobs(
                inventory,
                lambda run_id, _: {"total_count": 1, "jobs": [job(100 + run_id, 99)]},
            )

    def test_changed_job_page_or_missing_steps_fails_closed(self) -> None:
        inventory = collect_waiting_runs(pages([run(1)]), WORKFLOW_ID)
        calls = 0

        def changed(run_id: int, page: int) -> dict:
            nonlocal calls
            calls += 1
            return {"total_count": 1, "jobs": [job(101 if calls == 1 else 102, run_id)]}

        with self.assertRaises(IncompleteInventory):
            collect_waiting_jobs(inventory, changed)
        calls = 0

        def changed_status(run_id: int, page: int) -> dict:
            nonlocal calls
            calls += 1
            value = job(101, run_id)
            if calls == 2:
                value["status"] = "in_progress"
            return {"total_count": 1, "jobs": [value]}

        with self.assertRaises(IncompleteInventory):
            collect_waiting_jobs(inventory, changed_status)
        without_steps = job(101, 1)
        del without_steps["steps"]
        with self.assertRaises(IncompleteInventory):
            collect_waiting_jobs(
                inventory,
                lambda _run_id, _page: {"total_count": 1, "jobs": [without_steps]},
            )

    def test_missing_or_inconsistent_job_conclusion_fails_closed(self) -> None:
        inventory = collect_waiting_runs(pages([run(1)]), WORKFLOW_ID)
        for status, conclusion in (
            ("completed", None),
            ("completed", "unknown"),
            ("waiting", "success"),
            ("requested", "success"),
        ):
            with self.subTest(status=status, conclusion=conclusion):
                value = job(101, 1)
                value["status"] = status
                value["conclusion"] = conclusion
                with self.assertRaises(IncompleteInventory):
                    collect_waiting_jobs(
                        inventory,
                        lambda _run_id, _page, current=value: {"total_count": 1, "jobs": [current]},
                    )
        missing = job(101, 1)
        del missing["conclusion"]
        with self.assertRaises(IncompleteInventory):
            collect_waiting_jobs(inventory, lambda _run_id, _page: {"total_count": 1, "jobs": [missing]})


if __name__ == "__main__":
    unittest.main()
