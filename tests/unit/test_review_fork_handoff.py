"""Execute fork locators and protected native-identity fences without API effects."""

import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

import yaml

from unit import test_review_event_reconcile as reconcile_tests
from unit import test_review_protected_branch as branch_tests
from unit.review_event_contract_helpers import shell_function

ROOT = Path(__file__).resolve().parents[2]
REPO = "lightning-it/ansible-collection-supplementary"
FORK = "contributor/project-fork"
HEAD, BASE = "b" * 40, "a" * 40


class ForkHandoffTests(unittest.TestCase):
    def document(self, name):
        return yaml.safe_load((ROOT / ".github/workflows" / name).read_text())

    def pr(self, branch="develop"):
        return {
            "number": 23,
            "state": "open",
            "draft": False,
            "user": {"login": "contributor", "type": "User"},
            "head": {"sha": HEAD, "ref": "feature", "repo": {"full_name": FORK}},
            "base": {"sha": BASE, "ref": branch, "repo": {"full_name": REPO}},
        }

    def shell(self, code, env, pr=None, rows=None, jobs=None, pulls=None):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name, data in {"pr": pr, "rows": rows, "jobs": jobs, "pulls": pulls}.items():
                (root / name).write_text(json.dumps(data))
            gh = root / "gh"
            gh.write_text("""#!/usr/bin/env python3
import os,json,sys
from pathlib import Path
r=Path(os.environ['FIXTURE']);a=sys.argv[1:];route=' '.join(a)
with (r/'calls').open('a') as f:f.write(json.dumps(a)+'\\n')
if '--method' in a and a[a.index('--method')+1] != 'GET':
 if '/dispatches' not in route:raise SystemExit('unexpected write')
 print('{}')
elif '/branches/' in route:
 p=json.loads((r/'pr').read_text())
 branch=next(v for v in a if '/branches/' in v).split('/branches/')[1]
 source=os.environ.get('LIVE_SOURCE',p['base']['sha']) if branch=='develop' else p['base']['sha']
 print(json.dumps({'name':branch,'protected':True,'commit':{'sha':source}}))
elif '--jq' in a:print('develop')
elif '/jobs' in route:print((r/'jobs').read_text())
elif '/actions/runs?' in route:print((r/'rows').read_text())
elif 'state=open' in a:
 assert 'head=contributor:feature' in a,a
 print((r/'pulls').read_text())
elif '/pulls/' in route:print((r/'pr').read_text())
else:raise SystemExit('unexpected route '+route)
""")
            gh.chmod(0o755)
            result = subprocess.run(  # noqa: S603 -- Checked-in workflow shell with an offline fixture transport.
                ["/bin/bash", "-euo", "pipefail", "-c", code],
                env={**os.environ, "PATH": str(root) + ":" + os.environ["PATH"], "FIXTURE": td, **env},
                capture_output=True,
                text=True,
                check=False,
            )
            calls = (
                [json.loads(v) for v in (root / "calls").read_text().splitlines()] if (root / "calls").exists() else []
            )
            return result, calls

    def test_direct_event_handoff_keeps_fork_and_same_repo_verification_only(self):
        job = self.document("copilot-review.yml")["jobs"]["dispatch-event-verifier-reevaluation"]
        expression = " ".join(job["if"].replace("&&", " and ").replace("||", " or ").split())
        for branch in ("develop", "main"):
            for head_repo in (FORK, REPO):
                with self.subTest(branch=branch, head_repo=head_repo):
                    pr = self.pr(branch)
                    pr["head"]["repo"]["full_name"] = head_repo
                    github = NS(
                        repository=REPO,
                        event_name="pull_request_target",
                        ref_protected=True,
                        event=NS(
                            pull_request=NS(
                                user=NS(type="User"),
                                draft=False,
                                base=NS(repo=NS(full_name=REPO)),
                                head=NS(repo=NS(full_name=head_repo)),
                            )
                        ),
                    )
                    expression = expression.replace("needs.verify-current-revision-policy.result", "policy_result")
                    self.assertTrue(
                        eval(  # noqa: S307 -- Fixed checked-in workflow predicate, empty builtins and explicit fixture context.
                            expression,
                            {"__builtins__": {}},
                            {
                                "github": github,
                                "vars": NS(LI219_EVENT_MODE="enabled"),
                                "policy_result": "success",
                                "always": lambda: True,
                                "contains": lambda a, b: b in a,
                                "fromJSON": json.loads,
                                "false": False,
                                "true": True,
                            },
                        )
                    )

    def direct(self, branch, changed=None, live_source=None):
        pr = self.pr(branch)
        if changed:
            changed(pr)
        return self.shell(
            self.document("copilot-review.yml")["jobs"]["dispatch-event-verifier-reevaluation"]["steps"][0]["run"],
            {
                "REPOSITORY": REPO,
                "BASE_REF": branch,
                "BASE_SHA": BASE,
                "HEAD_SHA": HEAD,
                "HEAD_REF": "feature",
                "HEAD_REPOSITORY": FORK,
                "PR_AUTHOR": "contributor",
                "PR_NUMBER": "23",
                "WORKFLOW_SHA": ("e" * 40 if branch == "main" else BASE),
                "GITHUB_SHA": ("e" * 40 if branch == "main" else BASE),
                "GITHUB_WORKFLOW_REF": REPO + "/.github/workflows/copilot-review.yml@refs/heads/develop",
                "GITHUB_REF": "refs/heads/develop",
                "GITHUB_RUN_ID": "77",
                "GITHUB_RUN_ATTEMPT": "1",
                "LIVE_SOURCE": live_source or ("e" * 40 if branch == "main" else BASE),
            },
            pr,
        )

    def test_direct_handoff_actual_shell_and_identity_drift(self):
        for branch in ("develop", "main"):
            result, calls = self.direct(branch)
            self.assertEqual(0, result.returncode, result.stderr)
            posts = [c for c in calls if "POST" in c]
            self.assertEqual(1, len(posts))
            self.assertIn("ref=" + branch, posts[0])
            self.assertIn("inputs[producer_run_attempt]=1", posts[0])
            for change in (
                lambda p: p["head"]["repo"].update(full_name="another/same-sha-fork"),
                lambda p: p["head"]["repo"].clear(),
                lambda p: p["head"].update(ref="another"),
                lambda p: p["base"].update(sha="c" * 40),
                lambda p: p["user"].update(login="another"),
            ):
                result, calls = self.direct(branch, change)
                self.assertNotEqual(0, result.returncode)
                self.assertFalse(any("POST" in c for c in calls))
            result, calls = self.direct(branch, live_source="c" * 40)
            self.assertNotEqual(0, result.returncode)
            self.assertFalse(any("POST" in c for c in calls))

    def test_refresh_owner_election_binds_actual_fork_and_empty_association(self):
        function = shell_function(ROOT / ".github/workflows/copilot-review-refresh.yml", "elect_once")
        for branch in ("develop", "main"):
            for empty in (False, True):
                pr = self.pr(branch)
                entry = {
                    "number": 23,
                    "base": {"sha": BASE, "repo": {"url": "https://api.github.com/repos/" + REPO}},
                    "head": {"sha": HEAD, "ref": "feature", "repo": {"url": "https://api.github.com/repos/" + FORK}},
                }
                run = {
                    "id": 77,
                    "run_attempt": 1,
                    "status": "completed",
                    "conclusion": "success",
                    "event": "pull_request_target",
                    "path": ".github/workflows/copilot-review.yml",
                    "name": "Current revision review gate",
                    "head_branch": "feature",
                    "head_sha": HEAD,
                    "repository": {"full_name": REPO},
                    "head_repository": {"full_name": FORK},
                    "pull_requests": [] if empty else [entry],
                }
                jobs = [
                    {
                        "jobs": [
                            {
                                "id": 78,
                                "run_id": 77,
                                "run_attempt": 1,
                                "head_sha": HEAD,
                                "name": "Verify current revision policy",
                                "status": "completed",
                                "conclusion": "success",
                                "steps": [{"name": f"Event binding #23:{BASE}:{HEAD}:77"}],
                            }
                        ]
                    }
                ]
                env = {
                    "REPOSITORY": REPO,
                    "HEAD_REPOSITORY": FORK,
                    "EVENT_HEAD": HEAD,
                    "EVENT_BASE": BASE,
                    "LIVE_BASE": BASE,
                    "EVENT_HEAD_REF": "feature",
                    "PR_NUMBER": "23",
                    "PRODUCER_OWNER_MODE": "verification",
                }

                def call(r=run, ps=None, env=env, pr=pr, jobs=jobs):
                    return self.shell(
                        'oa() { gh api "$@"; }\n' + function + "\nelect_once",
                        env,
                        pr,
                        [{"workflow_runs": [r]}],
                        jobs,
                        [[pr]] if ps is None else ps,
                    )

                result, calls = call()
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("77", result.stdout.strip())
                altered = copy.deepcopy(run)
                altered["head_repository"]["full_name"] = "another/same-sha-fork"
                self.assertNotEqual(0, call(altered)[0].returncode)
                if empty:
                    self.assertNotEqual(0, call(ps=[[pr, {**pr, "number": 24}]])[0].returncode)
                else:
                    altered = copy.deepcopy(run)
                    altered["pull_requests"][0]["head"]["repo"]["url"] = (
                        "https://api.github.com/repos/another/same-sha-fork"
                    )
                    self.assertNotEqual(0, call(altered)[0].returncode)

    def test_refresh_forward_hydration_and_final_fence_bind_fork(self):
        fixture = branch_tests.ProtectedReviewBranchTests()
        for branch in ("develop", "main"):
            result, calls = fixture.refresh(branch, head_repository=FORK)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(1, len(calls))
            result, calls = fixture.refresh(branch, consumer=True, head_repository=FORK)
            self.assertEqual(0, result.returncode, result.stderr)
            result, calls = fixture.refresh(branch, final_fence=True, head_repository=FORK)
            self.assertEqual(0, result.returncode, result.stderr)
            for final in (False, True):
                result, calls = fixture.refresh(
                    branch, final_fence=final, head_repository=FORK, actual_head_repository="other/identical"
                )
                self.assertNotEqual(0, result.returncode)
                self.assertEqual([], calls)
            result, calls = fixture.refresh(branch, consumer=True, head_repository=FORK, execution_branch="foreign")
            self.assertNotEqual(0, result.returncode)
            self.assertEqual([], calls)
            result, calls = fixture.refresh(branch, consumer=True, head_repository=FORK, trigger_actor="untrusted")
            self.assertNotEqual(0, result.returncode)
            self.assertEqual([], calls)

    def test_periodic_fork_refresh_and_required_locator_with_no_paid_request(self):
        fixture = reconcile_tests.ReviewEventTests()
        for branch in ("develop", "main"):
            for neutral, path in ((False, "copilot-review-refresh.yml"), (True, "current-revision-rerun.yml")):
                calls = fixture.reconcile(base_ref=branch, head_repo=FORK, neutral=neutral)
                self.assertEqual(1, len(calls))
                self.assertTrue(calls[0][0].endswith(path + "/dispatches"))
                self.assertEqual(branch, calls[0][1]["ref"])
            self.assertEqual([], fixture.reconcile(base_ref=branch, head_repo=FORK, missing=True))
            self.assertEqual(
                [], fixture.reconcile(base_ref=branch, head_repo=FORK, producer_head_repo="another/same-sha-fork")
            )
            self.assertEqual(
                [], fixture.reconcile(base_ref=branch, head_repo=FORK, final_head_repo="another/same-sha-fork")
            )
            self.assertEqual([], fixture.reconcile(base_ref=branch, head_repo=FORK, drift=True))
            foreign = fixture.required_run()
            self.assertEqual([], fixture.reconcile(base_ref=branch, head_repo=FORK, neutral=True, required=[foreign]))
        for bad in ("", "owner", "owner/name/extra", "../name", "owner/name with spaces"):
            with self.subTest(head_repository=bad), self.assertRaises(ValueError):
                fixture.reconcile(head_repo=bad)

    def test_refresh_rejects_bot_forks_at_both_native_live_read_fences(self):
        fixture = branch_tests.ProtectedReviewBranchTests()
        for branch in ("develop", "main"):
            for mode in ({}, {"consumer": True}, {"final_fence": True}):
                with self.subTest(branch=branch, mode=mode):
                    result, calls = fixture.refresh(
                        branch, head_repository=FORK, author_type="Bot", **mode
                    )
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual([], calls)

    def test_paid_request_and_continuation_fork_exclusions_remain(self):
        workflow = self.document("copilot-review.yml")
        self.assertIn(
            "github.event.pull_request.head.repo.full_name == github.repository",
            workflow["jobs"]["request-current-revision-review"]["if"],
        )
        source = (ROOT / "scripts/review_request_continuation.py").read_text()
        self.assertIn('"litroc"', source)
        provenance = (ROOT / "scripts/review_request_provenance.py").read_text()
        self.assertIn('run["head_repository"]["full_name"] == repo', provenance)


if __name__ == "__main__":
    unittest.main()
