"""Exercise the real cross-verifier with bound ancestry and hostile evidence."""

from __future__ import annotations

import base64
import importlib.util
import json
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "ancestry_cross_fixtures", Path(__file__).with_name("test_dot_github_cross_controller.py")
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Cross-controller fixtures are unavailable")
FIXTURES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIXTURES)
MODULE = FIXTURES.MODULE
MAIN = "c" * 40
ROOT, BASE, HEAD = FIXTURES.TARGET, FIXTURES.BASE, FIXTURES.HEAD
MAIN_PATH = f"repos/{ROOT}/branches/main"
COMMIT_PATH = f"repos/{ROOT}/git/commits/{HEAD}"
COMPARE_PATH = f"repos/{ROOT}/compare/{BASE}...{HEAD}"
PROOF_PATH = f"repos/{ROOT}/contents/.lit/main-ancestry.json?ref={HEAD}"
NEUTRAL_PATH = f"repos/{ROOT}/commits/{HEAD}/check-runs?check_name=Current%20revision%20review&filter=all&per_page=100"


def set_proof(responses, proof):
    raw = json.dumps(proof).encode()
    responses[PROOF_PATH] = {
        "type": "file",
        "encoding": "base64",
        "size": len(raw),
        "content": base64.b64encode(raw).decode(),
    }


def fixture():
    responses = FIXTURES.valid_responses()
    pr = responses[FIXTURES.PR_PATH]
    pr["user"].update(id=307342877)
    pr["head"]["ref"] = f"backmerge/github-{MAIN[:12]}-{BASE[:12]}-main"
    pr["title"] = f"chore(governance): record main ancestry before {MAIN[:12]}"
    responses[f"repos/{ROOT}/actions/runs/{FIXTURES.RUN_ID}"]["head_branch"] = pr["head"]["ref"]
    neutral = responses[NEUTRAL_PATH]["check_runs"][0]
    summary = json.loads(neutral["output"]["summary"])
    summary.update(controller_sha=BASE, review_path=MODULE.ANCESTRY_REVIEW_PATH)
    neutral["output"]["summary"] = json.dumps(summary)
    neutral["output"]["title"] = "Current revision deterministic exemption passed"
    neutral["external_id"] = f"mlx90-current-revision:ancestry-backmerge:v6:{FIXTURES.PR_NUMBER}:42:{BASE}:{HEAD}"
    responses[MAIN_PATH] = {"name": "main", "protected": True, "commit": {"sha": MAIN}}
    responses[COMMIT_PATH] = {"sha": HEAD, "parents": [{"sha": BASE}, {"sha": MAIN}]}
    responses[COMPARE_PATH] = {
        "merge_base_commit": {"sha": BASE},
        "files": [{"filename": ".lit/main-ancestry.json", "status": "modified"}],
    }
    set_proof(
        responses,
        {
            "schema_version": 1,
            "repository": ROOT,
            "main_sha": MAIN,
            "develop_parent_sha": BASE,
            "purpose": "Bind the reviewed main ancestry backmerge.",
        },
    )
    environment = FIXTURES.valid_environment()
    environment.update(EVENT_TITLE_JSON=json.dumps(pr["title"]), EVENT_HEAD_REF=pr["head"]["ref"])
    return responses, environment


def verify(responses, environment):
    client = FIXTURES.FakeClient(responses)
    MODULE.verify(client, environment, attempts=1, sleep=lambda _: None)
    return client


class AncestryMetadataTests(unittest.TestCase):
    def test_accepts_real_ancestry_contract_and_revalidates_main_and_proof_twice(self):
        client = verify(*fixture())
        self.assertEqual(client.calls[MAIN_PATH], 2)
        self.assertEqual(client.calls[PROOF_PATH], 2)

    def test_rejects_release_app_for_root_ancestry_identity(self):
        responses, environment = fixture()
        responses[FIXTURES.PR_PATH]["user"].update(login=MODULE.RELEASE_APP_LOGIN, id=MODULE.RELEASE_APP_ID)
        environment.update(EVENT_AUTHOR=MODULE.RELEASE_APP_LOGIN)
        with self.assertRaises(MODULE.VerificationError):
            verify(responses, environment)

    def test_accepts_first_added_proof_but_rejects_removed_or_renamed_proof(self):
        responses, environment = fixture()
        responses[COMPARE_PATH]["files"][0]["status"] = "added"
        verify(responses, environment)
        for status in ("removed", "renamed", "copied", None):
            with self.subTest(status=status):
                responses, environment = fixture()
                responses[COMPARE_PATH]["files"][0]["status"] = status
                with self.assertRaises(MODULE.VerificationError):
                    verify(responses, environment)

    def test_rejects_wrong_title_identity_and_summary_contract(self):
        for mutation in ("title", "identity", "extra", "controller", "path", "schema"):
            with self.subTest(mutation=mutation):
                responses, environment = fixture()
                neutral = responses[NEUTRAL_PATH]["check_runs"][0]
                summary = json.loads(neutral["output"]["summary"])
                if mutation == "title":
                    neutral["output"]["title"] = "Current revision review passed"
                elif mutation == "identity":
                    neutral["external_id"] = neutral["external_id"].replace("ancestry-backmerge", "copilot")
                else:
                    field, value = {
                        "extra": ("pull_request_last_edited_at", None),
                        "controller": ("controller_sha", "d" * 40),
                        "path": ("review_path", "applicable Copilot or governed automation exemption"),
                        "schema": ("schema", 3),
                    }[mutation]
                    summary[field] = value
                neutral["output"]["summary"] = json.dumps(summary)
                with self.assertRaises(MODULE.VerificationError):
                    verify(responses, environment)

    def test_rejects_author_fork_base_branch_and_title_drift(self):
        for mutation in ("id", "login", "type", "fork", "base", "branch", "title"):
            with self.subTest(mutation=mutation):
                responses, environment = fixture()
                pr = responses[FIXTURES.PR_PATH]
                if mutation in {"id", "login", "type"}:
                    pr["user"][mutation] = {"id": 42, "login": "litroc", "type": "User"}[mutation]
                elif mutation == "fork":
                    pr["head"]["repo"]["full_name"] = "other/.github"
                elif mutation == "base":
                    pr["base"]["ref"] = "main"
                elif mutation == "branch":
                    pr["head"]["ref"] += "-changed"
                else:
                    pr["title"] += " changed"
                environment.update(
                    EVENT_AUTHOR=pr["user"]["login"],
                    EVENT_AUTHOR_TYPE=pr["user"]["type"],
                    EVENT_BASE_REF=pr["base"]["ref"],
                    EVENT_HEAD_REF=pr["head"]["ref"],
                    EVENT_TITLE_JSON=json.dumps(pr["title"]),
                )
                with self.assertRaises(MODULE.VerificationError):
                    verify(responses, environment)

    def test_rejects_parent_order_extra_content_and_unprotected_main(self):
        for mutation in ("reversed", "missing", "extra_parent", "extra_file", "wrong_path", "main", "merge_base"):
            with self.subTest(mutation=mutation):
                responses, environment = fixture()
                if mutation == "reversed":
                    responses[COMMIT_PATH]["parents"].reverse()
                elif mutation == "missing":
                    responses[COMMIT_PATH]["parents"].pop()
                elif mutation == "extra_parent":
                    responses[COMMIT_PATH]["parents"].append({"sha": "d" * 40})
                elif mutation == "extra_file":
                    responses[COMPARE_PATH]["files"].append({"filename": "code.py", "status": "modified"})
                elif mutation == "wrong_path":
                    responses[COMPARE_PATH]["files"][0]["filename"] = "code.py"
                elif mutation == "main":
                    responses[MAIN_PATH]["protected"] = False
                else:
                    responses[COMPARE_PATH]["merge_base_commit"]["sha"] = "d" * 40
                with self.assertRaises(MODULE.VerificationError):
                    verify(responses, environment)

    def test_rejects_proof_tuple_schema_shape_and_malformed_resource(self):
        for field, value in (
            ("main_sha", "d" * 40),
            ("develop_parent_sha", "d" * 40),
            ("repository", "other/.github"),
            ("schema_version", True),
            ("purpose", "skip review"),
            ("extra", "field"),
        ):
            with self.subTest(field=field):
                responses, environment = fixture()
                proof = json.loads(base64.b64decode(responses[PROOF_PATH]["content"]))
                proof[field] = value
                set_proof(responses, proof)
                with self.assertRaises(MODULE.VerificationError):
                    verify(responses, environment)
        for field, value in (("content", "!"), ("size", 4097), ("size", True), ("type", "symlink")):
            with self.subTest(resource_field=field):
                responses, environment = fixture()
                responses[PROOF_PATH][field] = value
                with self.assertRaises(MODULE.VerificationError):
                    verify(responses, environment)

    def test_rejects_live_main_drift_at_final_fence(self):
        responses, environment = fixture()
        responses[MAIN_PATH] = FIXTURES.ResponseSequence(
            responses[MAIN_PATH], {"name": "main", "protected": True, "commit": {"sha": "d" * 40}}
        )
        with self.assertRaises(MODULE.VerificationError):
            verify(responses, environment)

    def test_legacy_human_contract_remains_accepted(self):
        verify(FIXTURES.valid_responses(), FIXTURES.valid_environment())
