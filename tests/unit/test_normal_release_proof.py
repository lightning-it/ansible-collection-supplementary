"""Actual two-stage Git topology, native proof drift and workflow wiring tests."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("normal_release_proof", ROOT / "scripts/normal_release_proof.py")
PROOF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROOF)
REPOSITORY = "lightning-it/ansible-collection-supplementary"


class NativeControlPolicyContractTests(unittest.TestCase):
    def test_actual_adopted_producer_is_accepted_by_real_pinned_source(self):
        # Qualification loads the immutable donor checkout, never a mocked policy
        # or an inferred Git ancestry list. Generic source-only clones may omit
        # the separately staged offline fixture; that is not qualification.
        directory = Path(os.environ.get("LIT_RELEASE_CONTROL_FIXTURE", ROOT / ".cache/release-control-source"))
        if not directory.is_dir():
            self.skipTest("immutable offline native-control fixture not staged; qualification not executed")
        previous = sys.modules.pop("workflow_control", None)
        try:
            core = PROOF.load_control(directory)
            self.assertEqual((directory / "scripts/workflow_control.py").resolve(), Path(core.__file__).resolve())
            producer = "bb1a5df9f54c5f98547048297e7e367cc382543e"
            unknown = "0" * 40
            protected = json.loads((ROOT / ".lit/workflow-control.json").read_text())
            lineage = json.loads((directory / ".lit/workflow-source-lineage.json").read_text())
            self.assertNotIn(producer, lineage["accepted_predecessors"])
            self.assertNotIn(unknown, lineage["accepted_predecessors"])
            api = Mock()
            api.file.return_value = json.dumps(protected).encode()
            config = core.policy(api, REPOSITORY, "a" * 40, PROOF.CONTROL_SOURCE)
            api.file.assert_called_once_with(REPOSITORY, ".lit/workflow-control.json", "a" * 40)
            self.assertIn(producer, config["accepted_sources"])
            self.assertNotIn(unknown, config["accepted_sources"])
            self.assertEqual({producer, *lineage["accepted_predecessors"]}, set(config["accepted_sources"]))
            old_reader = core.policy(api, REPOSITORY, "a" * 40, "f263bac1a19c7b7a0f727e744c35360666925820")
            self.assertNotIn(producer, old_reader["accepted_sources"])
            protected["accepted_sources"] = [unknown]
            api.file.return_value = json.dumps(protected).encode()
            with self.assertRaisesRegex(core.ControlError, "consumer-cannot-admit-central-source"):
                core.policy(api, REPOSITORY, "a" * 40, PROOF.CONTROL_SOURCE)
            # The existing publisher pins the exact same defining source.
            workflow = yaml.safe_load((ROOT / ".github/workflows/collection-publish.yml").read_text())
            checkout = next(
                step
                for step in workflow["jobs"]["publish"]["steps"]
                if step.get("name") == "Checkout immutable public native-control verifier"
            )
            self.assertEqual(producer, checkout["with"]["ref"])
        finally:
            sys.modules.pop("workflow_control", None)
            if previous is not None:
                sys.modules["workflow_control"] = previous


class NormalReleaseProofTests(unittest.TestCase):
    def git(self, *args):
        executable = shutil.which("git")
        assert executable
        return (
            subprocess.check_output(  # noqa: S603 -- local isolated Git fixture.
                [executable, *args],
                cwd=self.root,
                env=self.git_env,
            )
            .decode()
            .strip()
        )

    def commit(self, message, parents):
        args = ["commit-tree", self.git("write-tree"), "-m", message]
        for parent in parents:
            args += ["-p", parent]
        return self.git(*args)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.git_env = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": PROOF.APP[0],
            "GIT_AUTHOR_EMAIL": PROOF.git_contract.CONTRACT.RELEASE_APP_EMAIL,
            "GIT_COMMITTER_NAME": PROOF.APP[0],
            "GIT_COMMITTER_EMAIL": PROOF.git_contract.CONTRACT.RELEASE_APP_EMAIL,
        }
        for variable in ("GIT_COMMON_DIR", "GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
            self.git_env.pop(variable, None)
        self.git("init", "--quiet")
        (self.root / "galaxy.yml").write_text("---\nnamespace: lit\nname: supplementary\nversion: 1.0.0\n")
        self.git("add", ".")
        self.main_base = self.commit("protected Main workflow source", [])
        self.git("checkout", "--quiet", "--detach", self.main_base)
        fragments = self.root / "changelogs/fragments"
        fragments.mkdir(parents=True)
        (fragments / "change.yml").write_text("---\nbugfixes:\n  - Reviewed change.\n")
        self.git("add", ".")
        self.content_base = self.commit("reviewed content ingress", [self.main_base])
        self.git("checkout", "--quiet", "--detach", self.content_base)
        version = PROOF.version_module()
        resolution = version.resolve_version(self.root / "galaxy.yml", fragments)
        self.receipt = version.build_preparation_receipt(
            resolution,
            repository=REPOSITORY,
            repository_id="1103407173",
            base_sha=self.content_base,
            workflow_run_id="10",
            workflow_attempt="1",
            workflow_ref=f"{REPOSITORY}/.github/workflows/release-prepare.yml@refs/heads/main",
            workflow_event="workflow_dispatch",
            workflow_actor="litroc",
            workflow_source_sha=self.main_base,
            root=self.root,
        )
        (self.root / PROOF.RECEIPT).write_bytes(PROOF.git_contract.CONTRACT.canonical_document_bytes(self.receipt))
        (self.root / "galaxy.yml").write_text("---\nnamespace: lit\nname: supplementary\nversion: 1.0.1\n")
        (fragments / "change.yml").unlink()
        self.git("add", "-A")
        self.prepared = self.commit("chore(release): prepare v1.0.1", [self.content_base])
        self.develop = self.commit("Merge preparation PR", [self.content_base, self.prepared])
        self.release = self.commit("Merge normal promotion PR", [self.main_base, self.develop])
        self.git("checkout", "--quiet", "--detach", self.release)
        self.prep = self.pull(1, self.develop, "develop", "release/v1.0.1", self.content_base, self.prepared)
        self.promotion = self.pull(2, self.release, "main", "develop", self.main_base, self.develop)
        self.ingress = {
            "run": 20,
            "attempt": 1,
            "job": 21,
            "head": self.prepared,
            "source_sha": PROOF.CONTROL_SOURCE,
            "route": "codex",
            "artifact": "control-proof-1",
            "proof_sha256": "a" * 64,
        }
        self.run = {
            "id": 30,
            "run_attempt": 1,
            "head_sha": self.develop,
            "status": "completed",
            "conclusion": "success",
            "workflow_id": 123,
            "workflow_url": "native-required",
            "path": "required",
        }
        self.proof = {
            "version": 1,
            "source_sha": PROOF.CONTROL_SOURCE,
            "route": "promotion",
            "binding": {"head": self.develop},
            "authorization": {"run": 30, "approval": {"user": "litroc"}},
            "evidence": {
                "base": self.main_base,
                "head": self.develop,
                "integration_tree": self.git("rev-parse", f"{self.release}^{{tree}}"),
                "ingress": [{"pull": 1, "merge": self.develop, "control": self.ingress}],
            },
        }
        self.api = Mock()
        self.api.pages.side_effect = self.pages
        self.api.call.side_effect = self.call
        self.core = Mock()
        self.core.policy.return_value = {"accepted_sources": [PROOF.CONTROL_SOURCE]}
        self.core.check_native_control.return_value = self.ingress
        self.core.ingress_candidates.return_value = [self.run]
        self.core.native_jobs.return_value = [{"name": "Current revision review", "conclusion": "success"}]
        self.core.artifact_record.return_value = self.proof
        self.core.binding.side_effect = lambda p: {"head": p["head"]["sha"]}
        self.core.operation_record.return_value = {"binding": {"head": self.develop}}
        self.core.same_immutable_tuple.side_effect = lambda a, b: a == b
        self.core.native_required.return_value = True
        self.core.native_approval.return_value = {"user": "litroc"}
        self.core.digest.side_effect = lambda p: hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()

    def pull(self, number, merge, base_ref, head_ref, base, head):
        return {
            "number": number,
            "state": "closed",
            "draft": False,
            "merged": True,
            "merged_at": "2026-10-18T00:00:00Z",
            "merge_commit_sha": merge,
            "user": dict(zip(("login", "id", "type"), PROOF.APP, strict=True)),
            "base": {"ref": base_ref, "sha": base, "repo": {"full_name": REPOSITORY}},
            "head": {"ref": head_ref, "sha": head, "repo": {"full_name": REPOSITORY}},
        }

    def pages(self, path, key=None):
        if f"commits/{self.develop}/pulls" in path:
            return [self.prep]
        if f"commits/{self.release}/pulls" in path:
            return [self.promotion]
        if "actions/runs?" in path:
            return [self.run]
        raise AssertionError(path)

    def call(self, path):
        if path.endswith("pulls/1"):
            return self.prep
        if path.endswith("pulls/2"):
            return self.promotion
        if path.endswith("actions/runs/30"):
            return self.run
        if path.endswith("actions/runs/10"):
            return {
                "id": 10,
                "run_attempt": 1,
                "repository": {"full_name": REPOSITORY},
                "head_repository": {"full_name": REPOSITORY},
                "head_sha": self.main_base,
                "head_branch": "main",
                "path": ".github/workflows/release-prepare.yml",
                "event": "workflow_dispatch",
                "actor": {"login": "litroc"},
                "status": "completed",
                "conclusion": "success",
            }
        if path.endswith("git/ref/heads/main"):
            return {"object": {"sha": self.release}}
        raise AssertionError(path)

    def publish(self):
        return PROOF.publish(
            self.root, self.api, self.core, REPOSITORY, "1103407173", self.release, self.main_base, self.develop
        )

    def test_actual_git_two_stage_and_native_coverage(self):
        result = self.publish()
        self.assertEqual(self.prepared, result["prepared_head"])
        self.assertEqual(self.content_base, result["content_base"])
        self.assertEqual(2, result["promotion_pr"])
        self.assertTrue(all(len(call.args) == 1 and not call.kwargs for call in self.api.call.call_args_list))
        self.core.check_native_control.assert_called_once()

    def test_proof_drift_and_missing_native_relations_fail_closed(self):
        original = copy.deepcopy(self.proof)
        for label, mutate in (
            ("route", lambda p: p.__setitem__("route", "codex")),
            ("source", lambda p: p.__setitem__("source_sha", "f" * 40)),
            ("approval", lambda p: p.__setitem__("authorization", None)),
            ("ingress", lambda p: p["evidence"].__setitem__("ingress", [])),
            ("tree", lambda p: p["evidence"].__setitem__("integration_tree", "a" * 40)),
        ):
            with self.subTest(label=label):
                self.proof = copy.deepcopy(original)
                mutate(self.proof)
                self.core.artifact_record.return_value = self.proof
                with self.assertRaises(ValueError):
                    self.publish()

    def test_wrong_app_fork_or_branch_rejected(self):
        original = copy.deepcopy(self.prep)
        for label, mutate in (
            ("author-id", lambda p: p["user"].__setitem__("id", 1)),
            ("fork", lambda p: p["head"]["repo"].__setitem__("full_name", "other/repo")),
            ("target", lambda p: p["base"].__setitem__("ref", "main")),
            ("prepared-head", lambda p: p["head"].__setitem__("sha", "a" * 40)),
        ):
            with self.subTest(label=label):
                self.prep = copy.deepcopy(original)
                mutate(self.prep)
                with self.assertRaises(ValueError):
                    self.publish()

    def test_pending_native_promotion_cannot_reuse_old_success(self):
        self.run["status"] = "in_progress"
        with unittest.mock.patch.dict(sys.modules, {"workflow_ingress": Mock()}):
            sys.modules["workflow_ingress"].merged_attempt.side_effect = ValueError("native-pending")
            with self.assertRaisesRegex(ValueError, "native-pending"):
                self.publish()

    def test_preparation_must_be_single_app_commit_and_generated_only(self):
        self.assertEqual(
            self.receipt,
            PROOF.preparation(self.root, self.content_base, self.prepared, self.main_base, REPOSITORY, "1103407173"),
        )
        (self.root / "executable.py").write_text("print('unreviewed')\n")
        self.git("add", ".")
        changed = self.commit("chore(release): prepare v1.0.1", [self.content_base])
        with self.assertRaisesRegex(ValueError, "non-generated"):
            PROOF.preparation(self.root, self.content_base, changed, self.main_base, REPOSITORY, "1103407173")
        with self.assertRaisesRegex(ValueError, "base SHA differs"):
            PROOF.preparation(self.root, self.main_base, self.prepared, self.main_base, REPOSITORY, "1103407173")

    def test_native_approval_is_rechecked(self):
        self.core.native_approval.return_value = {"user": "different"}
        with self.assertRaisesRegex(ValueError, "native-human-approval-drift"):
            self.publish()

    def test_changed_preparation_run_source_rejected(self):
        original = self.call

        def drift(path):
            result = original(path)
            if path.endswith("actions/runs/10"):
                result["head_sha"] = self.content_base
            return result

        self.api.call.side_effect = drift
        with self.assertRaisesRegex(ValueError, "protected-main-preparation-run"):
            self.publish()

    def test_squashed_or_later_develop_head_is_rejected(self):
        for head in (self.prepared, self.commit("later unbound Develop change", [self.develop])):
            with self.subTest(head=head):
                release = self.commit("promotion with wrong ingress shape", [self.main_base, head])
                self.git("checkout", "--quiet", "--detach", release)
                with self.assertRaisesRegex(ValueError, "exact-preparation-ingress-parents"):
                    PROOF.publish(
                        self.root, self.api, self.core, REPOSITORY, "1103407173", release, self.main_base, head
                    )

    def test_native_source_loading_requires_actual_pinned_clean_checkout(self):
        with self.assertRaisesRegex(ValueError, "pinned-control-source"):
            PROOF.load_control(self.root)

    def test_control_audit_observations_do_not_relabel_native_reference(self):
        recorded = copy.deepcopy(self.ingress)
        current = copy.deepcopy(self.ingress)
        current["post_merge_failed_attempts"] = [{"conclusion": "failure", "attempt": 2}]
        self.assertEqual(PROOF.control_reference(recorded), PROOF.control_reference(current))
        current["attempt"] = 2
        self.assertNotEqual(PROOF.control_reference(recorded), PROOF.control_reference(current))
        current["new_authority"] = True
        with self.assertRaisesRegex(ValueError, "reference-shape"):
            PROOF.control_reference(current)

    def test_newer_native_generation_is_rejected(self):
        newer = {**self.run, "run_attempt": 2}
        self.core.ingress_candidates.side_effect = [[self.run], [newer]]
        with self.assertRaisesRegex(ValueError, "newer-promotion-generation"):
            self.publish()

    def test_actual_readiness_steps_distinguish_consumed_unjoined_and_pending_tips(self):
        jobs = yaml.safe_load((ROOT / ".github/workflows/release-prepare.yml").read_text())["jobs"]
        steps = {step["id"]: step for step in jobs["normal-readiness"]["steps"] if "id" in step}
        self.git("remote", "add", "origin", str(self.root))
        (self.root / "scripts").mkdir()
        for name in ("release-version.py", "security_release_contract.py"):
            shutil.copyfile(ROOT / "scripts" / name, self.root / "scripts" / name)
        content = self.root / "release-readiness-content"
        (content / "changelogs/fragments").mkdir(parents=True)
        (content / "galaxy.yml").write_text("---\nversion: 1.0.1\n")
        pending = self.root / "changelogs/fragments/next.yml"
        pending.parent.mkdir(parents=True, exist_ok=True)
        pending.write_text("---\nbugfixes:\n  - Reviewed next change.\n")
        self.git("add", "changelogs/fragments/next.yml")
        unjoined = self.commit("next Develop ingress", [self.develop])
        joined = self.commit("next ingress after Main ancestry", [self.release])
        executable = shutil.which("bash")
        assert executable
        native = r"""gh() {
          printf '%s\n' "$2" >>"$NATIVE_CALLS"
          case "$2" in
            */branches/main) printf '{"protected":true,"commit":{"sha":"%s"}}\n' "$GITHUB_SHA";;
            */branches/develop) printf '{"protected":true,"commit":{"sha":"%s"}}\n' "$CONTENT_SHA";;
            */git/ref/heads/main) echo "$GITHUB_SHA";;
            */git/ref/heads/develop) echo "$CONTENT_SHA";;
            *) return 1;;
          esac
        }
        """
        for label, head, has_fragments, expected_status in (
            ("consumed-unjoined", self.develop, False, 0),
            ("pending-unjoined", unjoined, True, 1),
            ("pending-joined", joined, True, 0),
        ):
            with self.subTest(case=label):
                fragment = content / "changelogs/fragments/next.yml"
                if has_fragments:
                    fragment.write_bytes(pending.read_bytes())
                else:
                    fragment.unlink(missing_ok=True)
                calls = self.root / f"{label}-native-calls"
                output = self.root / f"{label}-output"
                environment = {
                    **self.git_env,
                    "GITHUB_REPOSITORY": REPOSITORY,
                    "GITHUB_SHA": self.release,
                    "CONTENT_SHA": head,
                    "VERSION_INPUT": "",
                    "BASE_INPUT": "",
                    "TARGET_INPUT": "",
                    "NATIVE_CALLS": str(calls),
                    "GITHUB_OUTPUT": str(output),
                }
                bind = subprocess.run(  # noqa: S603 -- actual read-only steps with offline native fixture.
                    [executable, "-c", native + steps["tips"]["run"]],
                    cwd=self.root,
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(0, bind.returncode, bind.stderr)
                self.assertEqual(f"content_sha={head}\n", output.read_text())
                output.unlink()
                need = subprocess.run(  # noqa: S603 -- actual Main parser and real Git topology.
                    [executable, "-c", native + steps["need"]["run"]],
                    cwd=self.root,
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(expected_status, need.returncode, need.stderr)
                if label == "consumed-unjoined":
                    self.assertEqual("ready=false\n", output.read_text())
                    self.assertIn("no-op", need.stdout)
                elif label == "pending-unjoined":
                    self.assertFalse(output.exists())
                else:
                    self.assertEqual("ready=true\n", output.read_text())
                native_reads = calls.read_text().splitlines()
                expected_reads = [f"repos/{REPOSITORY}/branches/main", f"repos/{REPOSITORY}/branches/develop"]
                if label == "pending-joined":
                    expected_reads += [
                        f"repos/{REPOSITORY}/git/ref/heads/main",
                        f"repos/{REPOSITORY}/git/ref/heads/develop",
                    ]
                self.assertEqual(expected_reads, native_reads)

    def test_standalone_preparation_cli_rejects_foreign_receipt_identity(self):
        for repository, repository_id, expected_error in (
            ("other/collection", "1103407173", "repository differs"),
            (REPOSITORY, "999999", "repository id differs"),
        ):
            with self.subTest(repository=repository, repository_id=repository_id):
                receipt = copy.deepcopy(self.receipt)
                receipt["repository"] = repository
                receipt["repository_id"] = repository_id
                receipt["workflow"]["ref"] = f"{repository}/.github/workflows/release-prepare.yml@refs/heads/main"
                (self.root / PROOF.RECEIPT).write_bytes(PROOF.git_contract.CONTRACT.canonical_document_bytes(receipt))
                self.git("add", PROOF.RECEIPT)
                foreign = self.commit("chore(release): prepare v1.0.1", [self.content_base])
                result = subprocess.run(  # noqa: S603 -- actual read-only CLI, fixed fixture arguments.
                    [
                        sys.executable,
                        str(ROOT / "scripts/normal_release_proof.py"),
                        "preparation",
                        "--root",
                        str(self.root),
                        "--base",
                        self.content_base,
                        "--head",
                        foreign,
                        "--workflow-source",
                        self.main_base,
                        "--repository",
                        REPOSITORY,
                        "--repository-id",
                        "1103407173",
                    ],
                    cwd=self.root,
                    env=self.git_env,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(0, result.returncode)
                self.assertIn(expected_error, result.stderr)

    def test_empty_fragment_guard_is_actual_noop(self):
        prepare = yaml.safe_load((ROOT / ".github/workflows/release-prepare.yml").read_text())["jobs"]
        step = next(step for step in prepare["normal-readiness"]["steps"] if step.get("id") == "need")
        (self.root / "release-readiness-content/changelogs/fragments").mkdir(parents=True)
        output = self.root / "readiness-output"
        executable = shutil.which("bash")
        assert executable
        result = subprocess.run(  # noqa: S603 -- actual protected read-only guard, offline Devtools.
            [executable, "-c", step["run"]],
            cwd=self.root,
            check=False,
            capture_output=True,
            text=True,
            env={**self.git_env, "GITHUB_OUTPUT": str(output)},
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("ready=false\n", output.read_text())
        self.assertIn("no-op", result.stdout)

    def test_readiness_uses_main_parser_and_rejects_unpublished_version_baseline(self):
        prepare = yaml.safe_load((ROOT / ".github/workflows/release-prepare.yml").read_text())["jobs"]
        step = next(step for step in prepare["normal-readiness"]["steps"] if step.get("id") == "need")
        (self.root / "scripts").mkdir()
        for name in ("release-version.py", "security_release_contract.py"):
            shutil.copyfile(ROOT / "scripts" / name, self.root / "scripts" / name)
        content = self.root / "release-readiness-content"
        (content / "changelogs/fragments").mkdir(parents=True)
        (content / "galaxy.yml").write_text("---\nversion: 1.0.0\n")
        (content / "changelogs/fragments/change.yml").write_text("---\nbugfixes:\n  - Reviewed fix.\n")
        output = self.root / "readiness-output"
        executable = shutil.which("bash")
        assert executable
        native = (
            'gh() { case "$2" in */heads/main) echo "$GITHUB_SHA";; '
            '*/heads/develop) echo "$CONTENT_SHA";; *) return 1;; esac; }\n'
        )
        for main_version, expected_status in (("1.0.0", 0), ("0.9.9", 1)):
            with self.subTest(main_version=main_version):
                output.unlink(missing_ok=True)
                (self.root / "galaxy.yml").write_text(f"---\nversion: {main_version}\n")
                result = subprocess.run(  # noqa: S603 -- offline parser and fake read-only native refs.
                    [executable, "-c", native + step["run"]],
                    cwd=self.root,
                    check=False,
                    capture_output=True,
                    text=True,
                    env={
                        **self.git_env,
                        "GITHUB_OUTPUT": str(output),
                        "VERSION_INPUT": "",
                        "GITHUB_REPOSITORY": REPOSITORY,
                        "GITHUB_SHA": self.main_base,
                        "CONTENT_SHA": self.content_base,
                    },
                )
                self.assertEqual(expected_status, result.returncode, result.stderr)
                if expected_status == 0:
                    self.assertEqual("ready=true\n", output.read_text())
                else:
                    self.assertFalse(output.exists())
                    self.assertIn("baseline differs", result.stdout)

    def test_legacy_normal_profile_cannot_create_missing_publications(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/collection-publish.yml").read_text())["jobs"]["publish"]
        steps = {step["name"]: step for step in workflow["steps"]}
        identity = steps["Verify protected-main and reviewed merge identity"]["run"]
        self.assertIn('git fetch --no-tags origin "refs/tags/${legacy_tag}"', identity)
        self.assertIn("releases/tags/${legacy_tag}", identity)
        self.assertIn(".draft == false and .prerelease == false", identity)
        for name, effect in (
            ("Create or verify immutable tag with dedicated App", "tag_object="),
            ("Create or verify GitHub Release and immutable assets", "gh release create"),
            ("Publish or verify validated artifact on Ansible Galaxy", "ansible-galaxy collection publish"),
        ):
            script = steps[name]["run"]
            self.assertLess(script.index("Legacy normal recheck cannot create"), script.index(effect))

    def test_workflow_executes_proof_and_gates_app_on_readiness(self):
        prepare = yaml.safe_load((ROOT / ".github/workflows/release-prepare.yml").read_text())["jobs"]
        self.assertNotIn("environment", prepare["normal-readiness"])
        self.assertIn("normal-readiness", prepare["prepare"]["needs"])
        self.assertIn("outputs.ready == 'true'", prepare["prepare"]["if"])
        script = "\n".join(step.get("run", "") for step in prepare["prepare"]["steps"])
        self.assertIn('"$workflow_source/scripts/normal_release_proof.py" preparation', script)
        self.assertIn('if [ "$REVIEW_ROUTE" = legacy ]; then\n  gh workflow', script)
        publish = yaml.safe_load((ROOT / ".github/workflows/collection-publish.yml").read_text())["jobs"]["publish"]
        steps = {step["name"]: step for step in publish["steps"]}
        proof = steps["Prove normal preparation ingress and exact approved promotion"]
        self.assertIn("normal_release_proof.py publish", proof["run"])
        self.assertEqual("env.NORMAL_TWO_STAGE == 'true'", proof["if"])


if __name__ == "__main__":
    unittest.main()
