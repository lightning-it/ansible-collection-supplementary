"""Execute root/default publication code with adversarial native API outcomes."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
GH = r"""#!/usr/bin/env python3
import copy, json, os, sys
from pathlib import Path
p = Path(os.environ['FIXTURE'])
d = json.loads(p.read_text())
a = sys.argv[1:]
method = a[a.index('--method')+1] if '--method' in a else 'GET'
route = next(x for x in a if x.startswith('repos/'))
f = dict(x.split('=',1) for x in a if '=' in x)
if method in ('POST','PATCH'):
    d['writes'].append([method, f.get('conclusion')])
    if any(key.startswith('output[') for key in f) and not all(
            key in f for key in ('output[title]', 'output[summary]')):
        d['invalid_output'] = True
        p.write_text(json.dumps(d)); sys.exit(1)
    previous = copy.deepcopy(d['check'])
    if method == 'POST' and d.get('unknown_post') == 'absent':
        p.write_text(json.dumps(d)); sys.exit(1)
    patch_kind = ('pending' if f.get('conclusion') == 'failure' and f.get('external_id') == 'bound-id'
                  else 'details' if method == 'PATCH' and list(f) == ['details_url'] else None)
    unknown_patch = d.get('unknown_' + patch_kind) if patch_kind else None
    if unknown_patch == 'absent':
        p.write_text(json.dumps(d)); sys.exit(1)
    if method == 'POST':
        d['check'] = {'id':79,'app':{'id':15368,'slug':'github-actions'},'output':{},'details_url':None}
    for key, value in f.items():
        if key.startswith('output['): d['check']['output'][key[7:-1]] = value
        else: d['check'][key] = value
    if ((method == 'POST' and d.get('drift_after_post'))
            or (f.get('conclusion') == 'success' and d.get('drift_after_promotion'))):
        d['valid'] = False
    if f.get('conclusion') == 'success' and d.get('head_drift_after_promotion'):
        d['pr']['head']['sha'] = 'd' * 40
    if f.get('conclusion') == 'success' and d.get('drift_field'):
        d[d['drift_field']] = False
    if method == 'PATCH' and (f.get('conclusion') or patch_kind == 'details' and d.get('details_stale')):
        d['stale_check'] = previous
        d['remaining_stale'] = d.get('details_stale', 0) if patch_kind == 'details' else d.get('stale_reads', 0)
        d['read_counts'] = d.get('read_counts', []) + [0]
    result = d['check']
    if (unknown_patch or (method == 'POST' and d.get('unknown_post'))
            or (f.get('conclusion') == 'success' and d.get('unknown_promotion'))):
        p.write_text(json.dumps(d)); sys.exit(1)
elif route.endswith('/pulls/23'):
    result = d['pr']
elif '/attempts/1/jobs?' in route:
    result = [{'total_count':1,'jobs':[{'id':78,'run_id':77,'run_attempt':1,'head_sha':'b'*40,
        'name':'Verify current revision policy','status':'completed','steps':[
        {'name':'Publish bound neutral result','status':'completed',
         'conclusion':d.get('previous_publish','failure')}]}]}]
elif '/commits/' in route:
    rows = [] if d['check'] is None else [d['check']]
    if rows and d.get('unknown_post') == 'ambiguous': rows.append({**rows[0], 'id':80})
    result = [{'total_count':len(rows),'check_runs':rows}]
elif '/check-runs/' in route:
    result = d['check']
    if d.get('read_counts'):
        d['read_counts'][-1] += 1
    if d.get('remaining_stale', 0):
        d['remaining_stale'] -= 1
        result = d['stale_check']
    if d.get('corrupt_read') and d.get('read_counts'):
        result = copy.deepcopy(result)
        if d['corrupt_read'] == 'evidence': result['output']['summary'] = 'wrong'
        else: result[d['corrupt_read']] = 'wrong'
else:
    result = {'valid':d['valid'], 'labels_valid':d.get('labels_valid', True),
              'review_valid':d.get('review_valid', True)}
p.write_text(json.dumps(d))
print(json.dumps(result))
"""


class NeutralPublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.temp = Path(temporary.name)
        self.fixture = self.temp / "fixture.json"
        self.data = {
            "check": None,
            "writes": [],
            "valid": True,
            "pr": {
                "number": 23,
                "state": "open",
                "draft": False,
                "title": "Review",
                "body": "Body",
                "head": {"sha": "b" * 40, "ref": "feature/test", "repo": {"full_name": "contributor/fork"}},
                "base": {
                    "sha": "c" * 40,
                    "ref": "develop",
                    "repo": {"full_name": "lightning-it/ansible-collection-supplementary"},
                },
            },
        }
        self.save()
        binary = self.temp / "bin"
        binary.mkdir()
        (binary / "gh").write_text(GH)
        (binary / "gh").chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": str(binary) + ":" + os.environ["PATH"],
            "FIXTURE": str(self.fixture),
            "REPOSITORY": "lightning-it/ansible-collection-supplementary",
            "PR_NUMBER": "23",
            "GITHUB_RUN_ID": "77",
            "GITHUB_RUN_ATTEMPT": "1",
            "EVENT_HEAD": "b" * 40,
            "EVENT_BASE": "c" * 40,
            "EVENT_ACTION": "opened",
            "GITHUB_SERVER_URL": "https://github.com",
            "BOUND_LABELS_SHA256": "labels",
            "BOUND_LAST_EDITED_AT": "null",
            "EVENT_TITLE": "Review",
            "EVENT_BODY": "Body",
            "EVENT_HEAD_REF": "feature/test",
            "EVENT_BASE_REF": "develop",
            "EVENT_HEAD_REPOSITORY": "contributor/fork",
        }
        self.workflow = ROOT / ".github/workflows/copilot-review.yml"

    def save(self):
        self.fixture.write_text(json.dumps(self.data))

    def publish(self, success=True):
        workflow = yaml.safe_load(self.workflow.read_text())
        step = next(
            s["run"]
            for s in workflow["jobs"]["verify-current-revision-policy"]["steps"]
            if s.get("name") == "Publish bound neutral result"
        )
        start = step.index("assert_bound_head_current() {")
        end = step.index("\nassert_bound_head_current\npublished_check_id=", start)
        script = (
            """set -euo pipefail
sleep() { :; }
api_read() { gh api "$@"; }
api_patch() { gh api --method PATCH "$@"; }
read_metadata_revision() {
  gh api "repos/${REPOSITORY}/live" | jq -r 'if .valid then "null" else "changed" end'
}
read_labels_sha256() {
  gh api "repos/${REPOSITORY}/live" | jq -r 'if .labels_valid then "labels" else "changed" end'
}
validate_bound_review() { gh api "repos/${REPOSITORY}/live" | jq -e .review_valid >/dev/null; }
run_url='https://github.com/lightning-it/ansible-collection-supplementary/actions/runs/77'
validate_bound_threads() { :; }
external_kind=copilot
result_title='Review verified'
evidence='{"schema":4,"producer_run_id":77}'
"""
            + step[start:end]
            + """
id="$(publish_once 'Current revision review' bound-id 'Review verified')" || exit $?
promote_publication "${id}" bound-id
"""
        )
        result = subprocess.run(  # noqa: S603 - execute the shipped publisher with isolated API stubs
            ["/bin/bash", "-c", script], env=self.env, capture_output=True, text=True, timeout=30, check=False
        )
        self.data = json.loads(self.fixture.read_text())
        self.assertEqual(success, result.returncode == 0, result.stderr + result.stdout)

    def test_root_and_default_publish_only_after_safe_readback_and_live_validation(self):
        for prefix in ("",):
            with self.subTest(prefix=prefix):
                self.setUp()
                self.workflow = ROOT / (prefix + ".github/workflows/copilot-review.yml")
                self.publish()
                self.assertEqual([["POST", "failure"], ["PATCH", None], ["PATCH", "success"]], self.data["writes"])

    def test_post_drift_remains_failure_and_promotion_drift_is_revoked_even_on_exit(self):
        for timing in ("drift_after_post", "drift_after_promotion"):
            with self.subTest(timing=timing):
                self.setUp()
                self.data[timing] = True
                self.save()
                self.publish(False)
                self.assertEqual("failure", self.data["check"]["conclusion"])
                self.assertEqual(1, sum(m == "POST" for m, _payload in self.data["writes"]))

    def test_unknown_create_exact_absent_ambiguous_and_later_attempt(self):
        for outcome in ("materialized", "absent", "ambiguous"):
            with self.subTest(outcome=outcome):
                self.setUp()
                self.data["unknown_post"] = outcome
                self.save()
                self.publish(outcome == "materialized")
                if outcome != "materialized":
                    self.assertEqual([["POST", "failure"]], self.data["writes"])
                self.env["GITHUB_RUN_ATTEMPT"] = "2"
                self.publish(outcome == "materialized")
                self.assertEqual(1, sum(m == "POST" for m, _payload in self.data["writes"]))

    def test_previously_attempted_pending_result_remains_get_only(self):
        self.data["drift_after_post"] = True
        self.save()
        self.publish(False)
        self.data.update(drift_after_post=False, valid=True)
        self.save()
        self.env["GITHUB_RUN_ATTEMPT"] = "2"
        writes = len(self.data["writes"])
        self.publish(False)
        self.assertEqual(1, sum(m == "POST" for m, _payload in self.data["writes"]))
        self.assertEqual("failure", self.data["check"]["conclusion"])
        self.assertEqual(writes, len(self.data["writes"]))

    def test_unknown_promotion_is_read_back_without_another_success_patch(self):
        self.data["unknown_promotion"] = True
        self.save()
        self.publish()
        self.assertEqual([["POST", "failure"], ["PATCH", None], ["PATCH", "success"]], self.data["writes"])

    def test_partial_output_objects_are_rejected_by_api_fixture(self):
        result = subprocess.run(  # noqa: S603 - execute only the temporary API fixture
            [
                str(self.temp / "bin" / "gh"),
                "api",
                "--method",
                "PATCH",
                "repos/example/check-runs/79",
                "-f",
                "output[title]=partial",
            ],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertTrue(json.loads(self.fixture.read_text())["invalid_output"])

    def test_stale_publication_converges_within_five_reads_without_write_retry(self):
        for prefix in ("",):
            for revoke in (False, True):
                with self.subTest(prefix=prefix, revoke=revoke):
                    self.setUp()
                    self.workflow = ROOT / (prefix + ".github/workflows/copilot-review.yml")
                    self.data.update(stale_reads=4, drift_after_promotion=revoke, unknown_promotion=True)
                    self.save()
                    self.publish(not revoke)
                    self.assertEqual([6, 5] if revoke else [5], self.data["read_counts"])
                    self.assertEqual(
                        [["POST", "failure"], ["PATCH", None], ["PATCH", "success"]]
                        + ([["PATCH", "failure"]] if revoke else []),
                        self.data["writes"],
                    )

    def test_persistent_stale_publication_exhausts_five_reads_without_write_retry(self):
        self.data.update(stale_reads=5, unknown_promotion=True)
        self.save()
        self.publish(False)
        self.assertEqual([5], self.data["read_counts"])
        self.assertEqual([["POST", "failure"], ["PATCH", None], ["PATCH", "success"]], self.data["writes"])

    def test_identity_and_evidence_mismatch_stop_on_first_read(self):
        for corruption in ("id", "head_sha", "external_id", "evidence"):
            with self.subTest(corruption=corruption):
                self.setUp()
                self.data.update(stale_reads=4, corrupt_read=corruption)
                self.save()
                self.publish(False)
                self.assertEqual([1], self.data["read_counts"])
                self.assertEqual(3, len(self.data["writes"]))

    def test_publication_rejects_live_pr_head_draft_or_closed_drift_before_create(self):
        for field in ("head", "draft", "state"):
            with self.subTest(field=field):
                self.setUp()
                if field == "head":
                    self.data["pr"]["head"]["sha"] = "d" * 40
                elif field == "draft":
                    self.data["pr"]["draft"] = True
                else:
                    self.data["pr"]["state"] = "closed"
                self.save()
                self.publish(False)
                self.assertEqual([], self.data["writes"])

    def test_head_drift_after_promotion_revokes_the_exact_old_head_without_write_retry(self):
        self.data["head_drift_after_promotion"] = True
        self.save()
        self.publish(False)
        self.assertEqual("failure", self.data["check"]["conclusion"])
        self.assertEqual(
            [["POST", "failure"], ["PATCH", None], ["PATCH", "success"], ["PATCH", "failure"]], self.data["writes"]
        )

    def test_unknown_pending_patch_materialized_absent_and_later_attempt_never_repeats(self):
        for outcome in ("materialized", "absent"):
            with self.subTest(outcome=outcome):
                self.setUp()
                self.data["check"] = {
                    "id": 79,
                    "name": "Current revision review",
                    "app": {"id": 15368, "slug": "github-actions"},
                    "head_sha": "b" * 40,
                    "status": "completed",
                    "conclusion": "failure",
                    "external_id": "old-bound-id",
                    "output": {"title": "Older binding", "summary": "older"},
                    "details_url": None,
                }
                self.data.update(unknown_pending=outcome, stale_reads=4)
                self.save()
                self.publish(outcome == "materialized")
                writes = len(self.data["writes"])
                self.env["GITHUB_RUN_ATTEMPT"] = "2"
                self.publish(outcome == "materialized")
                self.assertEqual(writes, len(self.data["writes"]))
                self.assertEqual(1, self.data["writes"].count(["PATCH", "failure"]))
                self.assertFalse(any(method == "POST" for method, _payload in self.data["writes"]))

    def test_unknown_details_patch_materialized_absent_and_later_attempt_never_repeats(self):
        for outcome in ("materialized", "absent"):
            with self.subTest(outcome=outcome):
                self.setUp()
                self.data.update(unknown_details=outcome, details_stale=4)
                self.save()
                self.publish(outcome == "materialized")
                writes = len(self.data["writes"])
                self.env["GITHUB_RUN_ATTEMPT"] = "2"
                self.publish(outcome == "materialized")
                self.assertEqual(writes, len(self.data["writes"]))
                self.assertEqual(1, self.data["writes"].count(["PATCH", None]))
                self.assertEqual(1, self.data["writes"].count(["POST", "failure"]))

    def test_only_natively_skipped_previous_publisher_can_start_attempt_two_writes(self):
        self.data["previous_publish"] = "skipped"
        self.env["GITHUB_RUN_ATTEMPT"] = "2"
        self.save()
        self.publish()
        self.assertEqual([["POST", "failure"], ["PATCH", None], ["PATCH", "success"]], self.data["writes"])

    def test_revocation_preserves_separate_diagnostic_flags(self):
        for field in ("valid", "labels_valid", "review_valid"):
            with self.subTest(field=field):
                self.setUp()
                self.data["drift_field"] = field
                self.save()
                self.publish(False)
                diagnostic = json.loads(self.data["check"]["output"]["summary"])
                for key in ("metadata_valid", "labels_valid", "review_valid"):
                    self.assertEqual(key != ("metadata_valid" if field == "valid" else field), diagnostic[key])
                self.assertIn(":binding-change:v1:", self.data["check"]["external_id"])


if __name__ == "__main__":
    unittest.main()
