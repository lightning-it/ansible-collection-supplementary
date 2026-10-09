"""Adversarial completeness checks for the read-only promotion run inventory."""

from __future__ import annotations

import unittest

from scripts.promotion_waiter_inventory import IncompleteInventory, collect_waiting_runs

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

    def test_foreign_workflow_and_missing_identity_fail_closed(self) -> None:
        foreign = run(1)
        foreign["workflow_id"] = WORKFLOW_ID + 1
        with self.assertRaises(IncompleteInventory):
            collect_waiting_runs(pages([foreign]), WORKFLOW_ID)
        missing_pr_inventory = run(1)
        del missing_pr_inventory["pull_requests"]
        with self.assertRaises(IncompleteInventory):
            collect_waiting_runs(pages([missing_pr_inventory]), WORKFLOW_ID)

    def test_filtered_api_limit_is_not_treated_as_complete(self) -> None:
        with self.assertRaises(IncompleteInventory):
            collect_waiting_runs(lambda _: {"total_count": 1000, "workflow_runs": []}, WORKFLOW_ID)


if __name__ == "__main__":
    unittest.main()
