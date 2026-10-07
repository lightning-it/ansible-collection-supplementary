"""Exercise the real remediation inspect caller without any external effects."""

import ast
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
HEAD = "a" * 40
LOGIN = "copilot-pull-request-reviewer[bot]"
WORKFLOW = ROOT / ".github/workflows/codex-copilot-remediation.yml"


class RemediationReviewContentTests(unittest.TestCase):
    def test_body_and_inline_use_the_canonical_marker_vocabulary(self):
        source = ROOT / "scripts/review_content_markers.py"
        if not source.exists():
            source = ROOT / "scripts/review_request_provenance.py"
        tree = ast.parse(source.read_text())
        canonical = next(
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "FAILURE_MARKERS"
        )
        workflow = WORKFLOW.read_text()
        predicate = workflow.split("review_content_usable() {", 1)[1].split("\n          }", 1)[0]
        markers = re.search(r'(\["unabletoreviewthispullrequest".*?\]) as \$markers', predicate, re.S)
        self.assertEqual(canonical, tuple(json.loads(markers[1])))
        self.assertEqual(2, len(re.findall(r"\| review_content_usable(?: true)?; then", workflow)))
        self.assertIn('contains("unabletoreview") or contains("notabletoreview")', predicate)
        mirror = ROOT / "default/.github/workflows/codex-copilot-remediation.yml"
        if mirror.exists():
            self.assertEqual(WORKFLOW.read_bytes(), mirror.read_bytes())

    def test_actual_inspect_requires_usable_content_before_eligibility_or_actionability(self):
        workflow = yaml.safe_load(WORKFLOW.read_text())
        script = workflow["jobs"]["inspect"]["steps"][0]["run"]
        current = {
            "author": {"login": LOGIN},
            "body": "Fix the incorrect return value.",
            "pullRequestReview": {"commit": {"oid": HEAD}},
        }

        def thread(comment):
            return {"isResolved": False, "comments": {"pageInfo": {"hasNextPage": False}, "nodes": [comment]}}

        stub = r"""gh() {
  printf '%s\n' "$*" >>"${CALLS}"
  case "$*" in
    'api repos/lightning-it/.github/pulls/23') printf '%s' "${PR}" ;;
    'api repos/lightning-it/.github/collaborators/litroc/permission --jq .permission') printf write ;;
    'api graphql '*) printf '%s' "${PAGE}" ;;
    'api --paginate --slurp repos/lightning-it/.github/issues/23/comments?per_page=100') printf '[[]]' ;;
    *) echo 'unexpected transport or mutation' >&2; return 99 ;;
  esac
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def inspect(body, comments):
                event = root / "event.json"
                output = root / "output"
                calls = root / "calls"
                output.write_text("")
                calls.write_text("")
                event.write_text(
                    json.dumps(
                        {
                            "pull_request": {"number": 23},
                            "review": {"body": body, "commit_id": HEAD, "user": {"login": LOGIN}},
                        }
                    )
                )
                pr = {
                    "state": "open",
                    "draft": False,
                    "base": {"ref": "develop"},
                    "head": {
                        "sha": HEAD,
                        "ref": "fix/example",
                        "label": "lightning-it:fix/example",
                        "repo": {"full_name": "lightning-it/.github"},
                    },
                    "user": {"login": "litroc"},
                }
                page = {
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "headRefOid": HEAD,
                                "reviewThreads": {
                                    "pageInfo": {"hasNextPage": False},
                                    "nodes": [thread(c) for c in comments],
                                },
                            }
                        }
                    }
                }
                env = {
                    **os.environ,
                    "GITHUB_EVENT_PATH": str(event),
                    "GITHUB_OUTPUT": str(output),
                    "GITHUB_REPOSITORY_OWNER": "lightning-it",
                    "REPOSITORY": "lightning-it/.github",
                    "COPILOT_LOGIN": LOGIN,
                    "PR": json.dumps(pr),
                    "PAGE": json.dumps(page),
                    "CALLS": str(calls),
                }
                result = subprocess.run(  # noqa: S603 -- fixed repository/fixture command and isolated environment.
                    ["bash", "-c", stub + script],  # noqa: S607 -- fixed shell in the pinned runtime.
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,  # noqa: S607 -- fixed executable from the pinned runtime.
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertNotIn("--method", calls.read_text())
                return dict(line.split("=", 1) for line in output.read_text().splitlines()), calls.read_text()

            for phrase in (
                "No files to review.",
                "No files were reviewed.",
                "NO FILES\u00a0WERE\nREVIEWED.",
                "I can't review this pull request.",
                "I can\u2019t review this pull request.",
                "I can't review any files.",
                "I can\u2019t review any files.",
                "I wasn't able to review any files.",
                "I wasn\u2019t able to review any files.",
                "I isn't able to review any files.",
                "I isn\u2019t able to review any files.",
            ):
                for body, comments in (
                    (phrase, []),
                    (phrase, [current]),
                    ("Review overview.", [{**current, "body": phrase}]),
                    (None, [{**current, "body": phrase}]),
                ):
                    with self.subTest(body=body, comments=comments):
                        values, calls = inspect(body, comments)
                        self.assertEqual({"eligible": "false", "actionable": "false"}, values)
                        self.assertNotIn("/issues/", calls)
            blanks = (None, "", " \t\n\u00a0\u2003")
            for body in blanks:
                for comments in (
                    [],
                    [{**current, "body": ""}],
                    [{**current, "body": " \t\n\u00a0\u2003"}],
                    [{**current, "author": {"login": "contributor"}}],
                    [{**current, "pullRequestReview": {"commit": {"oid": "b" * 40}}}],
                ):
                    with self.subTest(empty_body=body, comments=comments):
                        values, calls = inspect(body, comments)
                        self.assertEqual({"eligible": "false", "actionable": "false"}, values)
                        self.assertNotIn("/issues/", calls)
            for body in (*blanks, "Review overview."):
                values, _unused_value_1 = inspect(body, [current])
                self.assertEqual("true", values["eligible"])
                self.assertEqual("true", values["actionable"])
                self.assertEqual("1", values["round"])
            for comments in ([], [{**current, "body": ""}], [{**current, "body": " \t\n\u00a0\u2003"}]):
                values, _unused_value_2 = inspect("Review complete; no findings.", comments)
                self.assertEqual("true", values["eligible"])
                self.assertEqual("false", values["actionable"])
            valid, _unused_value_3 = inspect(None, [current])
            mixed, _unused_value_4 = inspect(None, [{**current, "body": " \u00a0"}, current, {**current, "body": ""}])
            self.assertEqual(valid["finding_hash"], mixed["finding_hash"])
            self.assertEqual("true", mixed["actionable"])
            # Unrelated/old comments do not become current-head failure evidence.
            values, _unused_value_5 = inspect(
                "Review overview.",
                [
                    current,
                    {**current, "body": "No files were reviewed.", "author": {"login": "contributor"}},
                    {**current, "body": "No files were reviewed.", "pullRequestReview": {"commit": {"oid": "b" * 40}}},
                ],
            )
            self.assertEqual("true", values["actionable"])
