"""Execute protected workflow paths for the third native release review findings.

Offline native fixtures exercise data binding only and confer no admission.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from tests.unit import test_normal_release_back_sync as BACKSYNC

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = "lightning-it/ansible-collection-supplementary"
APP = {"login": "lightning-it-release-automation[bot]", "id": 307565056, "type": "Bot"}


def step(workflow, job, name):
    """Read the actual workflow rather than maintaining a second shell copy."""
    document = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text())
    return next(value for value in document["jobs"][job]["steps"] if value.get("name") == name)


def environment():
    """Do not inherit linked-worktree Git routing into independent fixtures."""
    return {key: value for key, value in os.environ.items() if not key.startswith("GIT_")} | {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "BASH_ENV": os.devnull,
    }


def shell(script, cwd, env):
    return subprocess.run(  # noqa: S603 -- actual fixed workflow shell, private offline fixture.
        ["/bin/bash", "-euo", "pipefail", "-c", script],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


class ProtectedPythonProcessTests(unittest.TestCase):
    def test_candidate_shadow_modules_never_run_in_either_yaml_transform(self):
        script = step("release-prepare.yml", "prepare", "Prepare release branch")["run"]
        blocks = re.findall(r"(?m)^python[^\n]* <<'PY'\n.*?^PY$", script, re.DOTALL)
        transforms = [block for block in blocks if "LintFriendlyDumper" in block]
        self.assertEqual(2, len(transforms))
        for block in transforms:
            with self.subTest(block=block.splitlines()[0]), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "changelogs").mkdir()
                (root / "galaxy.yml").write_text("version: 1.0.0\n")
                (root / "changelogs/changelog.yaml").write_text("releases: {}\n")
                (root / "changelogs/.plugin-cache.yaml").write_text("plugins: {}\n")
                marker = root / "candidate-code-ran"
                (root / "yaml.py").write_text(
                    "import os\nfrom pathlib import Path\n"
                    "Path(os.environ['SHADOW_MARKER']).write_text(os.environ['GH_TOKEN'])\n"
                    "raise RuntimeError('candidate module executed')\n"
                )
                result = shell(
                    block,
                    root,
                    environment()
                    | {
                        "PYTHONPATH": str(root),
                        "SHADOW_MARKER": str(marker),
                        "GH_TOKEN": "offline-credential-sentinel",
                        "VERSION": "1.0.1",
                    },
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertFalse(marker.exists(), "Develop module observed the privileged environment")
                expected = "1.0.1" if "version = os.environ" in block else "1.0.0"
                self.assertEqual(expected, yaml.safe_load((root / "galaxy.yml").read_text())["version"])

    def test_two_fresh_control_processes_preserve_the_actual_pinned_checkout(self):
        source = Path(os.environ.get("LIT_RELEASE_CONTROL_FIXTURE", ROOT / ".cache/release-control-source"))
        if not source.is_dir():
            self.skipTest("immutable bb1 fixture not staged; native-control qualification not executed")
        script = yaml.safe_load((ROOT / ".github/workflows/promote-develop-to-main.yml").read_text())
        guard = (
            script["jobs"]["promote"]["steps"][-1]["run"]
            .split("# LI-139 release-state guard:start\n", 1)[1]
            .split("# LI-139 release-state guard:end", 1)[0]
        )
        exports = "\n".join(line for line in guard.splitlines() if line.startswith("export "))
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory) / "control"
            env = environment()
            env.pop("PYTHONDONTWRITEBYTECODE", None)
            subprocess.run(  # noqa: S603 -- immutable local fixture clone, never network.
                ["/usr/bin/git", "clone", "--quiet", "--no-hardlinks", str(source), str(clone)],
                env=env,
                check=True,
                capture_output=True,
            )
            loader = (
                "import sys;from pathlib import Path;"
                f"sys.path.insert(0,{str(ROOT / 'scripts')!r});"
                "import normal_release_proof as proof;"
                "core=proof.load_control(Path(sys.argv[1]));"
                "assert callable(core.policy)"
            )
            command = [sys.executable, "-c", loader, str(clone)]

            # Reproduce the reviewed failure with the old two-process path.
            old = shell(shlex.join(command) + "\n" + shlex.join(command), directory, env)
            self.assertNotEqual(0, old.returncode)
            self.assertIn("clean-control-source-required", old.stderr)
            subprocess.run(  # noqa: S603 -- remove only generated fixture bytecode.
                ["/usr/bin/git", "-C", str(clone), "clean", "-fd"],
                env=env,
                check=True,
                capture_output=True,
            )
            actual = exports + "\n" + shlex.join(command) + "\n" + shlex.join(command)
            result = shell(actual, directory, env)
            self.assertEqual(0, result.returncode, result.stderr)
            status = subprocess.check_output(  # noqa: S603 -- read-only local Git fixture.
                ["/usr/bin/git", "-C", str(clone), "status", "--porcelain"],
                env=env,
                text=True,
            )
            self.assertEqual("", status)
            (clone / "untrusted-file").write_text("must still fail\n")
            result = shell(actual, directory, env)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("clean-control-source-required", result.stderr)


class ProtectedGeneratorTests(unittest.TestCase):
    def test_real_git_plugin_or_config_delta_stops_before_credentialed_job(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/release-prepare.yml").read_text())
        preflight = next(
            value["run"] for value in workflow["jobs"]["normal-readiness"]["steps"] if value.get("id") == "need"
        )
        guard = preflight.split("# LI-344 generator closure:start\n", 1)[1].split("# LI-344 generator closure:end", 1)[
            0
        ]
        self.assertIn("needs.normal-readiness.outputs.ready == 'true'", workflow["jobs"]["prepare"]["if"])
        for name in (
            "plugins/doc_fragments/new.py",
            "plugins/modules/new.py",
            "collections/ansible_collections/evil/plugin.py",
            "ansible.cfg",
            "changelogs/config.yaml",
            "meta/runtime.yml",
            "roles/new/meta/argument_specs.yml",
            "roles/new/tasks/main.yml",
        ):
            with self.subTest(path=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                env = environment()

                def git(*args, cwd=root, environ=env):
                    return subprocess.check_output(  # noqa: S603 -- local fixed Git fixture.
                        ["/usr/bin/git", *args],
                        cwd=cwd,
                        env=environ,
                        text=True,
                    ).strip()

                git("init", "-q")
                git("config", "user.name", "Fixture")
                git("config", "user.email", "fixture@example.com")
                (root / "ordinary").write_text("base")
                git("add", ".")
                git("commit", "-qm", "base")
                base = git("rev-parse", "HEAD")
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("candidate-controlled code or output escape")
                git("add", ".")
                git("commit", "-qm", "candidate")
                head = git("rev-parse", "HEAD")
                result = shell(guard, root, env | {"GITHUB_SHA": base, "CONTENT_SHA": head})
                self.assertNotEqual(0, result.returncode)
                self.assertIn("ordinary Main convergence", result.stdout)
                result = shell(guard, root, env | {"GITHUB_SHA": head, "CONTENT_SHA": head})
                self.assertEqual(0, result.returncode, result.stderr)

    def test_generator_uses_main_cwd_config_and_only_fixed_candidate_data(self):
        script = step("release-prepare.yml", "prepare", "Prepare release branch")["run"]
        guard = script.split("# LI-344 protected generator:start\n", 1)[1].split("# LI-344 protected generator:end", 1)[
            0
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate, tooling, binary = (root / name for name in ("candidate", "main", "bin"))
            for tree in (candidate, tooling):
                (tree / "changelogs/fragments").mkdir(parents=True)
                (tree / "galaxy.yml").write_text("namespace: lit\nname: supplementary\nversion: 1.0.1\n")
                (tree / "changelogs/changelog.yaml").write_text("releases: {}\n")
                (tree / "changelogs/.plugin-cache.yaml").write_text("plugins: {}\n")
                (tree / "changelogs/fragments/change.yml").write_text("bugfixes: [fixture]\n")
                (tree / "CHANGELOG.rst").write_text("old\n")
            (tooling / "changelogs/config.yaml").write_text("output: [{file: CHANGELOG.rst, format: rst}]\n")
            # The untrusted escape and Python module must never reach tooling.
            verifier = tooling / "verifier.py"
            verifier.write_text("trusted Main verifier\n")
            (candidate / "changelogs/config.yaml").write_text(f"output: [{{file: {verifier}, format: rst}}]\n")
            (candidate / "yaml.py").write_text("raise RuntimeError('candidate Python imported')\n")
            binary.mkdir()
            command = binary / "antsibull-changelog"
            command.write_text(
                "#!"
                + sys.executable
                + "\n"
                + r"""
import os,sys
from pathlib import Path
assert Path.cwd()==Path(os.environ['workflow_source'])
assert 'verifier.py' not in Path('changelogs/config.yaml').read_text()
assert not Path('yaml.py').exists()
if sys.argv[1]=='release':
    Path('CHANGELOG.rst').write_text('new generated changelog\n')
    Path('changelogs/changelog.yaml').write_text('releases: {1.0.1: {}}\n')
    Path('changelogs/.plugin-cache.yaml').write_text('plugins: {}\n')
    Path('changelogs/fragments/change.yml').unlink()
"""
            )
            command.chmod(0o700)
            result = shell(
                guard,
                candidate,
                environment()
                | {
                    "PATH": f"{binary}:{os.environ['PATH']}",
                    "workflow_source": str(tooling),
                    "GH_TOKEN": "offline-sentinel",
                },
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("trusted Main verifier\n", verifier.read_text())
            self.assertEqual("new generated changelog\n", (candidate / "CHANGELOG.rst").read_text())
            self.assertFalse((candidate / "changelogs/fragments/change.yml").exists())
            self.assertTrue((candidate / "yaml.py").exists())

    def test_symlink_write_target_fails_before_parser_or_generator(self):
        script = step("release-prepare.yml", "prepare", "Prepare release branch")["run"]
        guard = script.split("# LI-344 regular generation inputs:start\n", 1)[1].split(
            "# LI-344 regular generation inputs:end", 1
        )[0]
        self.assertLess(script.index("# LI-344 regular generation inputs:end"), script.index('version_resolution="$('))
        for name in (
            "galaxy.yml",
            "CHANGELOG.rst",
            "changelogs/release-preparation.json",
            "changelogs/fragments/change.yml",
        ):
            with self.subTest(path=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "changelogs/fragments").mkdir(parents=True)
                outside = root / "protected-verifier"
                outside.write_text("trusted")
                path = root / name
                path.symlink_to(outside)
                result = shell(guard, root, environment())
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("trusted", outside.read_text())


class PublishDispatchNoopTests(unittest.TestCase):
    def run_case(self, *, changed_version=False, changed_state=False, bad_author=False, legacy=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "gh"
            binary.write_text(
                "#!"
                + sys.executable
                + "\n"
                + r"""
import base64,json,os,sys
from pathlib import Path
args=sys.argv[1:]
with Path(os.environ['CALLS']).open('a') as stream: stream.write(json.dumps(args)+'\n')
if args[0]!='api' or any(a in args for a in ['POST','PATCH','DELETE']): raise SystemExit('write forbidden')
path=args[1]; state=json.loads(os.environ['STATE'])
if '/git/ref/' in path: print('a'*40)
elif '/git/commits/' in path: print(json.dumps({'parents':[{'sha':'b'*40},{'sha':'c'*40}]}))
elif '/contents/' in path:
    name=path.split('/contents/',1)[1].split('?')[0]; base=path.endswith('b'*40)
    if name=='galaxy.yml':
        version='1.0.1' if not base and state['changed_version'] else '1.0.0'
        value='version: '+version+'\ndependencies: '+('{}' if base else '{lit.other: 2.0.0}')+'\n'
    else:
        receipt={'schema_version':3,'release_mode':'normal',
            'next_version':('1.0.1' if state['changed_version'] else '1.0.0'),
            'publication':{'github_release':True,'galaxy':True}}
        value=json.dumps(receipt) if name.endswith('.json') else 'generated\n'
    if '--jq' in args:
        expression=args[args.index('--jq')+1]
        encoded=base64.b64encode(value.encode()).decode()
        blob='different' if not base and state['changed_state'] else name
        print(encoded if expression=='.content' else blob)
    else: raise SystemExit('contents must select an explicit data field')
else: raise SystemExit('unexpected API locator '+path)
"""
            )
            binary.chmod(0o700)
            output = root / "output"
            calls = root / "calls"
            calls.write_text("")
            result = shell(
                step("collection-publish.yml", "dispatch", "Verify reviewed merge and derive publishing settings")[
                    "run"
                ],
                root,
                environment()
                | {
                    "PATH": f"{root}:{os.environ['PATH']}",
                    "STATE": json.dumps({"changed_version": changed_version, "changed_state": changed_state}),
                    "CALLS": str(calls),
                    "GITHUB_OUTPUT": str(output),
                    "RUNNER_TEMP": str(root),
                    "GITHUB_REPOSITORY": REPOSITORY,
                    "MERGE_SHA": "a" * 40,
                    "REVIEWED_HEAD_SHA": "c" * 40,
                    "HEAD_REF": "release/v1.0.0" if legacy else "develop",
                    "HEAD_REPOSITORY": REPOSITORY,
                    "PR_AUTHOR": APP["login"],
                    "PR_AUTHOR_TYPE": "Bot",
                    "PR_AUTHOR_ID": "1" if bad_author else str(APP["id"]),
                    "PR_BODY": "",
                    "GH_TOKEN": "offline-read-only",
                },
            )
            return (
                result,
                dict(line.split("=", 1) for line in output.read_text().splitlines()) if output.exists() else {},
                calls.read_text(),
            )

    def test_metadata_only_main_promotion_noops_before_every_later_step(self):
        result, outputs, _unused = self.run_case()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("false", outputs.get("release_needed"))
        self.assertNotIn("release_version", outputs)
        workflow = yaml.safe_load((ROOT / ".github/workflows/collection-publish.yml").read_text())
        for later in workflow["jobs"]["dispatch"]["steps"][1:]:
            self.assertEqual("steps.release.outputs.release_needed == 'true'", later.get("if"), later["name"])

    def test_real_release_state_change_and_legacy_dispatch_are_preserved(self):
        for changes in ({"changed_version": True}, {"changed_state": True}, {"legacy": True}):
            with self.subTest(changes=changes):
                result, outputs, _unused = self.run_case(**changes)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("true", outputs.get("release_needed"))
                self.assertIn("release_version", outputs)

    def test_noop_is_not_a_branch_name_or_foreign_author_exemption(self):
        result, outputs, _unused = self.run_case(bad_author=True)
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("release_needed", outputs)


class CanonicalAncestryOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.fixture = BACKSYNC.NormalBackSyncTests("runTest")
        self.fixture.setUp()
        self.fixture.fixture.git_env["BASH_ENV"] = os.devnull
        self.addCleanup(self.fixture.doCleanups)
        self.addCleanup(self.fixture.tearDown)

    def run_sync_guard(self, *, ordinary=False, schema=3, github_release=True, wrong_app=False):
        fixture = self.fixture
        script = step("sync-main-to-develop.yml", "backmerge", "Create reviewable ancestry backmerge")["run"]
        if "# LI-344 normal ancestry owner:start" not in script:
            self.fail("actual sync still has no normal-release single-writer fence")
        guard = script.split("# LI-344 normal ancestry owner:start\n", 1)[1].split(
            "# LI-344 normal ancestry owner:end", 1
        )[0]
        receipt = fixture.fixture.receipt.copy()
        receipt.update(
            {
                "schema_version": schema,
                "release_mode": "normal",
                "next_version": "1.0.1",
                "publication": {"github_release": github_release},
            }
        )
        # Only the guard's Git inputs are replaced; Git relationships and PR
        # binding come from the same real two-parent release used by back-sync.
        original = fixture.git("show", f"{fixture.release}:changelogs/release-preparation.json")
        self.assertEqual(3, json.loads(original)["schema_version"])
        binary = fixture.root / "sync-gh"
        binary.mkdir(exist_ok=True)
        gh = binary / "gh"
        pr = {
            "number": 12,
            "merged": True,
            "merged_at": "2026-10-18T00:00:00Z",
            "state": "closed",
            "draft": False,
            "merge_commit_sha": fixture.release,
            "user": {**APP, "id": 1 if wrong_app else APP["id"]},
            "base": {
                "ref": "main",
                "sha": fixture.fixture.main_base,
                "repo": {"full_name": REPOSITORY, "id": 1103407173},
            },
            "head": {"ref": "develop", "sha": fixture.develop, "repo": {"full_name": REPOSITORY, "id": 1103407173}},
        }
        gh.write_text(
            "#!"
            + sys.executable
            + "\nimport json,os,sys\np=json.loads(os.environ['SYNC_PR'])\n"
            + "print(json.dumps([[p]] if any('/commits/' in a for a in sys.argv) else p))\n"
        )
        gh.chmod(0o700)
        # Bind a real variant commit for non-release and legacy fallthrough.
        main = fixture.release
        if ordinary or schema != 3 or not github_release:
            fixture.git("checkout", "-q", "--detach", fixture.release)
            if ordinary:
                path = fixture.root / "galaxy.yml"
                path.write_text(path.read_text() + "dependencies: {lit.other: 2.0.0}\n")
                fixture.git("add", str(path))
                product = fixture.fixture.commit("ordinary product metadata", [fixture.release])
                main = fixture.fixture.commit("ordinary reviewed promotion", [fixture.release, product])
            else:
                path = fixture.root / "changelogs/release-preparation.json"
                path.write_text(json.dumps(receipt))
                fixture.git("add", str(path))
                main = fixture.fixture.commit("fixture variant", [fixture.fixture.main_base, fixture.develop])
        result = shell(
            guard + "\necho ORDINARY_ANCESTRY_WRITER\n",
            fixture.root,
            environment()
            | {
                "PATH": f"{binary}:{os.environ['PATH']}",
                "SYNC_PR": json.dumps(pr),
                "REPOSITORY": REPOSITORY,
                "REPOSITORY_ID": "1103407173",
                "GITHUB_REF": "refs/heads/main",
                "GITHUB_SHA": main,
                "main_sha": main,
                "develop_sha": fixture.develop,
            },
        )
        return result

    def exercise_order(self, sync_first):
        if sync_first:
            result = self.run_sync_guard()
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertNotIn("ORDINARY_ANCESTRY_WRITER", result.stdout)
            self.assertEqual("", self.fixture.branches())
        result, _unused = self.fixture.run_step()
        self.assertEqual(0, result.returncode, result.stderr)
        head = self.fixture.state["pull"]["head"]["sha"]
        result = self.run_sync_guard()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("ORDINARY_ANCESTRY_WRITER", result.stdout)
        self.assertEqual(head, self.fixture.state["pull"]["head"]["sha"])
        self.assertEqual("", self.fixture.git("diff", "--name-only", self.fixture.develop, head))

    def test_sync_first_leaves_one_fresh_canonical_writer(self):
        self.exercise_order(True)

    def test_publication_first_leaves_one_fresh_canonical_writer(self):
        self.exercise_order(False)

    def test_ordinary_legacy_and_unpublished_modes_keep_existing_ancestry_path(self):
        for changes in ({"ordinary": True}, {"schema": 2}, {"github_release": False}):
            with self.subTest(changes=changes):
                result = self.run_sync_guard(**changes)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("ORDINARY_ANCESTRY_WRITER", result.stdout)

    def test_shape_without_real_app_relationship_is_closed_before_any_writer(self):
        result = self.run_sync_guard(wrong_app=True)
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("ORDINARY_ANCESTRY_WRITER", result.stdout)
        self.assertEqual("", self.fixture.branches())
