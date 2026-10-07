"""Actual review-content classifiers only; no transport or provider effects."""

import ast
import json
import os
import re
import shutil
import subprocess
import unittest

from unit.review_event_contract_helpers import ROOT, shell_function

NEGATIVES = (
    "I can't review this pull request.",
    "I can\u2019t review this pull request.",
    "I can't review any files.",
    "I can\u2019t review any files.",
    "I wasn't able to review any files.",
    "I wasn\u2019t able to review any files.",
    "I isn't able to review any files.",
    "I isn\u2019t able to review any files.",
)
POSITIVE = "I can review any files."
WORKFLOWS = (
    ".github/workflows/copilot-review.yml",
    ".github/workflows/copilot-review-refresh.yml",
    ".github/workflows/codex-copilot-remediation.yml",
)


class CannotReviewClassifierTests(unittest.TestCase):
    def canonical(self):
        names = {"FAILURE_MARKERS", "ReviewContentError", "normalize", "require_usable_review_content"}
        parsed = ast.parse((ROOT / "scripts/review_content_markers.py").read_text())
        selected = [
            node
            for node in parsed.body
            if getattr(node, "name", None) in names
            or isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in names
        ]
        namespace = {}
        exec(compile(ast.Module(body=selected, type_ignores=[]), "actual-pure-classifier", "exec"), namespace)  # noqa: S102 -- selected literal/constants and pure function definitions only.
        return namespace

    def run_jq(self, program, payload, args=()):
        result = subprocess.run(  # noqa: S603 -- actual readonly classifier and local JSON fixture.
            [shutil.which("jq") or "jq", *args, program],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout.strip()

    def test_python_and_every_actual_jq_contraction_chain_agree(self):
        canonical = self.canonical()
        self.assertIn("cannotreviewthispullrequest", canonical["FAILURE_MARKERS"])
        self.assertIn("cannotreviewanyfiles", canonical["FAILURE_MARKERS"])
        chains = []
        for name in WORKFLOWS:
            text = (ROOT / name).read_text()
            chains.extend(re.findall(r'gsub\("can\[.*?\]t"; "cannot"\) \| gsub\("n\[.*?\]t"; " not"\)', text))
            self.assertEqual(text.count('gsub("n['), text.count('gsub("can['), name)
        self.assertEqual(5, len(chains))
        for phrase in (*NEGATIVES, POSITIVE):
            normalized = canonical["normalize"](phrase)
            for chain in chains:
                self.assertEqual(
                    normalized,
                    json.loads(self.run_jq("ascii_downcase | " + chain + r' | gsub("\\s"; "")', phrase)),
                )
            for inline in (False, True):
                if phrase == POSITIVE:
                    canonical["require_usable_review_content"](phrase, [])
                else:
                    with self.assertRaises(canonical["ReviewContentError"]):
                        canonical["require_usable_review_content"](
                            "Reviewed." if inline else phrase, [phrase] if inline else []
                        )

    def test_actual_publisher_content_counts_reject_body_and_inline_negatives(self):
        text = (ROOT / WORKFLOWS[0]).read_text()
        program = re.search(r"'(def normalize_review_text:.*?\| @tsv)'", text, re.S)[1]
        args = ["-r"]
        for key, value in (
            ("unable_marker", "Unable to review this pull request"),
            ("no_files_marker", "No files were reviewed"),
            ("quota_exhausted_marker", "Quota exhausted"),
            ("quota_exceeded_marker", "Quota exceeded"),
            ("suppressed_comments_marker", "Suppressed comments"),
        ):
            args.extend(("--arg", key, value))
        for phrase in (*NEGATIVES, POSITIVE):
            for inline in (False, True):
                node = {
                    "body": "Reviewed." if inline else phrase,
                    "comments": {"nodes": [{"body": phrase}] if inline else []},
                }
                counts = self.run_jq(program, {"data": {"node": node}}, args).split()
                self.assertEqual("0" if phrase == POSITIVE else "1", counts[0])

    def test_actual_legacy_refresh_jq_and_shell_case_reject_body_and_inline(self):
        function = shell_function(ROOT / WORKFLOWS[1], "review_body_is_usable")
        script = 'gh() { printf "%s" "$COMMENTS"; }\n' + function + '\nreview_body_is_usable <<<"$REVIEW"'
        for phrase in (*NEGATIVES, POSITIVE):
            for inline in (False, True):
                result = subprocess.run(  # noqa: S603 -- actual local function; transport emits only fixed fixture JSON.
                    [shutil.which("bash") or "/bin/bash", "-c", script],
                    env={
                        **os.environ,
                        "REPOSITORY": "lightning-it/ansible-collection-supplementary",
                        "PR_NUMBER": "23",
                        "REVIEW_ID": "17",
                        "REVIEW": json.dumps({"body": "Reviewed." if inline else phrase}),
                        "COMMENTS": json.dumps([[{"body": phrase, "pull_request_review_id": 17}]] if inline else [[]]),
                    },
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(phrase == POSITIVE, result.returncode == 0, result.stderr)
