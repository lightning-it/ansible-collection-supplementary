"""Regression tests for the collection's GitHub Actions trust boundaries."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
ACTION = ROOT / ".github" / "actions" / "run-quality-profile" / "action.yml"
SCORECARD_ACTION = ROOT / ".github" / "actions" / "run-scorecard" / "action.yml"
PINNED_USE = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
PINNED_DOCKER_USE = re.compile(r"^docker://[^@\s]+@sha256:[0-9a-f]{64}$")


def load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError(f"{path} is not a YAML mapping")
    return payload


def uses_values(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if key == "uses" and isinstance(nested, str):
                found.append(nested)
            found.extend(uses_values(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(uses_values(nested))
    return found


def docker_action_image(path: Path) -> str | None:
    payload = load_yaml(path)
    runs = payload.get("runs")
    if not isinstance(runs, dict) or runs.get("using") != "docker":
        return None
    image = runs.get("image")
    return image if isinstance(image, str) else None


class WorkflowSecurityTests(unittest.TestCase):
    def test_quality_cells_install_only_the_prebuilt_exact_candidate(self) -> None:
        action = ACTION.read_text(encoding="utf-8")
        install = re.search(
            r"ansible-galaxy collection install \\\n(?P<body>(?:\s+.*\n){1,8})",
            action,
        )
        self.assertIsNotNone(install)
        command = install.group(0) if install is not None else ""
        self.assertIn('"${candidates[0]}"', command)
        self.assertIn("--force", command)
        self.assertIn("--no-deps", command)
        self.assertIn("runtime-collections.tar.gz", action)
        self.assertIn('path.parts[0] != "ansible_collections"', action)
        self.assertIn("member.issym()", action)
        self.assertIn("member.islnk()", action)
        self.assertIn("absolute runtime collection link", action)
        self.assertIn("escaping runtime collection link", action)
        self.assertIn("duplicate runtime collection member", action)
        self.assertIn('"members": members', action)
        self.assertIn('extract_arguments["filter"] = "data"', action)
        self.assertIn("C.COLLECTIONS_PATHS", action)
        self.assertIn("missing declared runtime collections", action)
        self.assertIn(
            "ANSIBLE_COLLECTIONS_PATH=$QUALITY_INSTALL_ROOT:$default_collection_paths",
            action,
        )
        workflow = (WORKFLOWS / "collection-ci.yml").read_text(encoding="utf-8")
        self.assertIn("-czf dist/candidate/runtime-collections.tar.gz", workflow)
        self.assertIn("--exclude=ansible_collections/lit/supplementary", workflow)
        self.assertIn("for path, _ in members", workflow)
        self.assertIn("runtime collection bundle contains the candidate collection", workflow)
        self.assertIn("runtime-collections.tar.gz \\", workflow)

    def test_release_evidence_selects_only_the_collection_candidate_and_exact_head(self) -> None:
        workflow = (WORKFLOWS / "collection-ci.yml").read_text(encoding="utf-8")
        self.assertIn("-name 'lit-supplementary-*.tar.gz'", workflow)
        self.assertNotIn(
            "find artifacts/candidate -maxdepth 1 -type f -name '*.tar.gz'",
            workflow,
        )
        payload = load_yaml(WORKFLOWS / "collection-ci.yml")
        self.assertNotIn("QUALITY_SOURCE_SHA", payload["env"])
        self.assertEqual(
            payload["env"]["SOURCE_SHA"],
            payload["jobs"]["runtime-evidence"]["env"]["QUALITY_SOURCE_SHA"],
        )

    def test_keycloak_cells_reserve_memory_for_the_full_runtime_stack(self) -> None:
        collection = load_yaml(WORKFLOWS / "collection-ci.yml")
        candidate = load_yaml(WORKFLOWS / "candidate-platform-validation.yml")
        tiny_action = next(
            step
            for step in collection["jobs"]["tiny-cells"]["steps"]
            if step.get("uses") == "./.github/actions/run-quality-profile"
        )
        self.assertEqual("12GiB", tiny_action["with"]["memory-limit"])
        for job in ("heavy-cells", "acceptance-cells"):
            with self.subTest(job=job):
                delegated = collection["jobs"][job]
                self.assertIn("lightning-it/modulix-validation/", delegated["uses"])
                self.assertNotIn("memory-limit", delegated["with"])
        self.assertEqual(
            "12GiB",
            candidate["jobs"]["candidate-cells"]["steps"][1]["with"]["memory-limit"],
        )
        for scenario in ("keycloak-tiny", "keycloak-heavy", "keycloak-application-acceptance"):
            with self.subTest(scenario=scenario):
                molecule = (ROOT / "molecule" / scenario / "molecule.yml").read_text(encoding="utf-8")
                self.assertIn("${KEYCLOAK_TEST_MEMORY_LIMIT:-12GiB}", molecule)

    def test_copilot_and_renovate_gates_preserve_safe_update_boundaries(self) -> None:
        copilot = (WORKFLOWS / "copilot-review.yml").read_text(encoding="utf-8")
        renovate = (WORKFLOWS / "renovate-guarded-automerge.yml").read_text(encoding="utf-8")
        changelog = (WORKFLOWS / "changelog.yml").read_text(encoding="utf-8")

        self.assertIn('([.labels[].name] | index("safe-automerge") != null)', copilot)
        self.assertIn('([.labels[].name] | index("breaking-update") == null)', copilot)
        self.assertIn("(.head.sha == $head_sha)", copilot)
        self.assertIn("for attempt in $(seq 1 40)", copilot)
        self.assertIn(".isResolved == false", copilot)
        self.assertIn("expected_safe_event=$'labeled\\tsafe-automerge\\trenovate[bot]'", renovate)
        self.assertIn('[ "$safe_event" = "$expected_safe_event" ]', renovate)
        self.assertIn('grep -Fq "$breaking_event_pattern"', renovate)
        self.assertIn('[ "$PR_AUTHOR" = "renovate[bot]" ]', changelog)
        self.assertIn('[ "$PR_BASE" = "develop" ]', changelog)
        self.assertIn('[[ "$PR_HEAD" = renovate/* ]]', changelog)
        self.assertIn('index("renovate") != null', changelog)
        self.assertIn('index("dependencies") != null', changelog)
        self.assertIn('index("safe-automerge") != null', changelog)
        self.assertIn('index("breaking-update") == null', changelog)

    def test_collection_ci_concurrency_isolated_by_pr_and_exact_head(self) -> None:
        workflow = load_yaml(WORKFLOWS / "collection-ci.yml")
        top_group = workflow["concurrency"]["group"]
        self.assertIn("github.repository", top_group)
        self.assertIn("github.workflow", top_group)
        self.assertIn("github.event.pull_request.number || github.ref", top_group)
        self.assertNotIn("head.sha", top_group)
        self.assertEqual(
            "${{ github.event_name == 'pull_request' }}",
            workflow["concurrency"]["cancel-in-progress"],
        )

        jobs = workflow["jobs"]
        tiny_group = jobs["tiny-cells"]["concurrency"]["group"]
        self.assertIn("github.repository", tiny_group)
        self.assertIn("github.workflow", tiny_group)
        self.assertIn("github.event.pull_request.number || github.ref", tiny_group)
        self.assertIn("github.event.pull_request.head.sha || github.sha", tiny_group)

        for name, profile in (
            ("heavy-cells", "heavy"),
            ("acceptance-cells", "application_acceptance"),
        ):
            delegated = jobs[name]
            self.assertRegex(
                delegated["uses"],
                r"^lightning-it/modulix-validation/\.github/workflows/"
                r"collection-quality-profile\.yml@[0-9a-f]{40}$",
            )
            self.assertEqual(profile, delegated["with"]["profile"])
            self.assertIn("quality-matrix.outputs", delegated["with"]["matrix-json"])
            self.assertIn(
                "github.event.pull_request.head.sha || github.sha",
                delegated["with"]["source-sha"],
            )

    def test_all_workflows_and_local_actions_require_release_team_review(self) -> None:
        codeowners = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
        rules = {
            line.split("#", maxsplit=1)[0].strip()
            for line in codeowners.splitlines()
            if line.split("#", maxsplit=1)[0].strip()
        }
        self.assertIn(
            "/.github/workflows/** @lightning-it/ent:release",
            rules,
        )
        self.assertIn(
            "/.github/actions/** @lightning-it/ent:release",
            rules,
        )
        for path in (
            "/meta/quality-impact.yml",
            "/scripts/quality_cell_identity.py",
            "/scripts/select-quality-impact.py",
            "/scripts/source_dependencies.py",
            "/scripts/validate-role-coverage.py",
        ):
            self.assertIn(f"{path} @lightning-it/ent:release", rules)

    def test_every_external_action_is_commit_pinned(self) -> None:
        paths = sorted(WORKFLOWS.glob("*.yml")) + sorted((ROOT / ".github" / "actions").rglob("*.yml"))
        uses = [item for path in paths for item in uses_values(load_yaml(path))]
        external = [item for item in uses if not item.startswith(("./", "docker://"))]
        docker = [item for item in uses if item.startswith("docker://")]
        docker.extend(image for path in paths if (image := docker_action_image(path)) is not None)
        self.assertTrue(external)
        self.assertEqual([], [item for item in external if PINNED_USE.fullmatch(item) is None])
        self.assertTrue(docker)
        self.assertEqual(
            [],
            [item for item in docker if PINNED_DOCKER_USE.fullmatch(item) is None],
        )

    def test_release_credentials_are_outside_pull_request_jobs(self) -> None:
        jobs = load_yaml(WORKFLOWS / "collection-ci.yml")["jobs"]
        release_security = jobs["release-security"]
        self.assertEqual("ansible-collection-release-evidence", release_security["environment"])
        self.assertEqual(
            "github.event_name == 'push' && github.ref == 'refs/heads/main'",
            release_security["if"],
        )
        self.assertEqual("write", release_security["permissions"]["id-token"])
        self.assertEqual({"contents": "read"}, jobs["runtime-evidence"]["permissions"])

        aws_secret = "QUALITY_EVIDENCE_AWS_ACCESS_KEY_ID"  # noqa: S105
        self.assertIn(aws_secret, json.dumps(release_security))
        untrusted_jobs = {name: job for name, job in jobs.items() if name != "release-security"}
        self.assertNotIn(aws_secret, json.dumps(untrusted_jobs))

    def test_self_hosted_pr_cells_require_exact_head_and_protected_environment(self) -> None:
        jobs = load_yaml(WORKFLOWS / "collection-ci.yml")["jobs"]
        for name in ("tiny-cells", "heavy-cells", "acceptance-cells"):
            guard = jobs[name]["if"]
            self.assertIn(
                "needs.quality-matrix.outputs.keycloak_required == 'true'",
                guard,
            )
            self.assertIn("github.event.pull_request.head.repo.full_name == github.repository", guard)
            self.assertIn("github.event.pull_request.base.ref == 'develop'", guard)
            self.assertIn("github.event.pull_request.head.ref == 'develop'", guard)
            self.assertIn(
                "startsWith(github.event.pull_request.head.ref, 'release/v')",
                guard,
            )
            self.assertRegex(
                " ".join(guard.split()),
                r"base\.ref == 'main'.*head\.ref == 'develop'.*startsWith\(",
            )
            self.assertIn("github.event_name == 'push'", guard)
            self.assertNotIn("github.event_name == 'schedule'", guard)
            self.assertIn("inputs.execution_mode == 'nightly-develop'", guard)
            if name == "tiny-cells":
                environment = jobs[name]["environment"]["name"]
            else:
                environment = jobs[name]["with"]["environment-name"]
            self.assertIn("ansible-collection-runtime-tests", environment)
            self.assertIn("ansible-collection-runtime-protected", environment)
        runtime_guard = jobs["runtime-evidence"]["if"]
        self.assertIn("always()", runtime_guard)
        self.assertIn(
            "needs.quality-matrix.outputs.keycloak_required == 'true'",
            runtime_guard,
        )
        self.assertIn("pull_request.head.repo.full_name == github.repository", runtime_guard)
        self.assertIn(
            "startsWith(github.event.pull_request.head.ref, 'release/v')",
            runtime_guard,
        )
        serialized = json.dumps(load_yaml(WORKFLOWS / "collection-ci.yml"))
        self.assertIn("github.event.pull_request.head.sha || github.sha", serialized)
        self.assertNotIn("runtime is deferred", serialized)
        self.assertNotIn("Privileged self-hosted execution is deferred", serialized)
        for name in ("tiny", "heavy", "acceptance"):
            self.assertIn(
                'test "$PROFILE_RESULT" = success',
                jobs[name]["steps"][0]["run"],
            )
            self.assertIn(
                'test "$PROFILE_RESULT" = skipped',
                jobs[name]["steps"][0]["run"],
            )
        quality_outputs = jobs["quality-matrix"]["outputs"]
        self.assertIn("keycloak_required", quality_outputs)
        self.assertIn("full_matrix", quality_outputs)
        self.assertIn("selection", quality_outputs)
        evidence_gate = jobs["evidence"]["steps"][0]["run"]
        self.assertIn('test "$RUNTIME_EVIDENCE_RESULT" = success', evidence_gate)
        self.assertIn('test "$RUNTIME_EVIDENCE_RESULT" = skipped', evidence_gate)
        stable_names = {
            jobs[name]["name"]
            for name in (
                "lint-sanity",
                "build-install",
                "tiny",
                "heavy",
                "acceptance",
                "role-coverage",
                "evidence",
                "release-validation",
            )
        }
        self.assertEqual(
            {
                "Collection / Lint and Sanity",
                "Collection / Build and Install",
                "Collection / Tiny",
                "Collection / Heavy",
                "Collection / Application Acceptance",
                "Collection / Role Coverage",
                "Collection / Evidence",
                "Collection / Release Validation",
            },
            stable_names,
        )
        legacy_names = {
            jobs[name]["name"]
            for name in (
                "keycloak-legacy-lint-sanity",
                "keycloak-legacy-tiny",
                "keycloak-legacy-heavy",
                "keycloak-legacy-acceptance",
                "keycloak-legacy-evidence",
                "keycloak-legacy-release-validation",
            )
        }
        self.assertEqual(
            {
                "Keycloak / Lint and Sanity",
                "Keycloak / Tiny",
                "Keycloak / Heavy",
                "Keycloak / Application Acceptance",
                "Keycloak / Evidence",
                "Keycloak / Release Validation",
            },
            legacy_names,
        )

    def test_candidate_platforms_run_only_as_non_release_promotion_input(self) -> None:
        path = WORKFLOWS / "candidate-platform-validation.yml"
        workflow = load_yaml(path)
        # PyYAML 1.1 treats the plain YAML key `on` as boolean true.
        trigger = workflow.get("on", workflow.get(True))
        self.assertEqual({"schedule", "workflow_dispatch"}, set(trigger))
        self.assertNotIn("pull_request", trigger)
        jobs = workflow["jobs"]
        source = jobs["source"]
        self.assertIn("github.event_name == 'schedule'", source["if"])
        source_step = json.dumps(source["steps"])
        self.assertIn("git/ref/heads/develop", source_step)
        self.assertIn("source_ref=refs/heads/develop", source_step)
        self.assertEqual("source", jobs["matrix"]["needs"])
        self.assertEqual("source", jobs["build"]["needs"])
        self.assertIn("source", jobs["candidate-cells"]["needs"])
        self.assertEqual(
            "ansible-collection-runtime-protected",
            jobs["candidate-cells"]["environment"],
        )
        self.assertIn(
            "needs.source.outputs.sha",
            json.dumps(jobs["candidate-cells"]),
        )
        self.assertEqual(
            "Candidate platform / Promotion input only",
            jobs["promotion-input"]["name"],
        )
        serialized = json.dumps(workflow)
        self.assertIn("target-disposition", serialized)
        self.assertIn("candidate", serialized)
        self.assertIn("promotion input only", serialized)
        self.assertIn("not release evidence", serialized)

        nightly = load_yaml(WORKFLOWS / "nightly-develop.yml")
        trigger = nightly.get("on", nightly.get(True))
        self.assertIn("schedule", trigger)
        dispatch = json.dumps(nightly["jobs"]["dispatch"])
        self.assertIn("git/ref/heads/develop", dispatch)
        self.assertIn("--ref develop", dispatch)
        self.assertIn("execution_mode=nightly-develop", dispatch)

    def test_composite_shell_never_interpolates_untrusted_inputs_directly(self) -> None:
        action = load_yaml(ACTION)
        run_scripts = [
            step["run"]
            for step in action["runs"]["steps"]
            if isinstance(step, dict) and isinstance(step.get("run"), str)
        ]
        self.assertTrue(run_scripts)
        self.assertFalse(any("${{ inputs." in script for script in run_scripts))

    def test_publish_mutation_is_protected_and_scorecard_is_immutable(self) -> None:
        publish = load_yaml(WORKFLOWS / "collection-publish.yml")["jobs"]["publish"]
        self.assertEqual("ansible-collections", publish["environment"])
        self.assertIn("github.ref == 'refs/heads/main'", publish["if"])
        self.assertEqual("write", publish["permissions"]["contents"])
        self.assertEqual("write", publish["permissions"]["id-token"])
        self.assertEqual("write", publish["permissions"]["actions"])
        serialized_publish = json.dumps(publish)
        self.assertNotIn("LITRELEASEBOT_TOKEN", serialized_publish)
        self.assertNotIn("steps.token.outputs.value", serialized_publish)
        self.assertIn("github.token", serialized_publish)
        first_step = publish["steps"][0]
        self.assertEqual(
            "Enforce dedicated release-tag principal configuration",
            first_step["name"],
        )
        self.assertIn("RELEASE_TAG_APP_ID", json.dumps(first_step))
        self.assertIn("RELEASE_TAG_APP_CLIENT_ID", json.dumps(first_step))
        self.assertIn("RELEASE_TAG_APP_INSTALLATION_ID", json.dumps(first_step))
        self.assertIn("RELEASE_TAG_APP_PRIVATE_KEY", json.dumps(first_step))

        token_step = next(
            step
            for step in publish["steps"]
            if step.get("name") == "Mint exact repository-scoped release-tag App token"
        )
        self.assertEqual(
            "actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1",
            token_step["uses"],
        )
        self.assertEqual("write", token_step["with"]["permission-contents"])
        self.assertIn("github.event.repository.name", token_step["with"]["repositories"])

        validate_step = next(
            step for step in publish["steps"] if step.get("name") == "Validate exact release-tag App installation"
        )
        self.assertIn("/apps/${ACTION_APP_SLUG}", validate_step["run"])
        self.assertNotIn("gh api /installation", validate_step["run"])
        self.assertIn("EXPECTED_APP_CLIENT_ID", json.dumps(validate_step))
        self.assertIn("/installation/repositories?per_page=100", validate_step["run"])
        self.assertIn(".total_count == 1", validate_step["run"])
        tag_step = next(
            step for step in publish["steps"] if step.get("name") == "Create or verify immutable tag with dedicated App"
        )
        self.assertEqual(
            "${{ steps.release-tag-token.outputs.token }}",
            tag_step["env"]["GH_TOKEN"],
        )
        self.assertIn("/git/refs", tag_step["run"])
        self.assertNotIn("gh release", tag_step["run"])
        release_step = next(
            step
            for step in publish["steps"]
            if step.get("name") == "Create or verify GitHub Release and immutable assets"
        )
        self.assertEqual("${{ github.token }}", release_step["env"]["GH_TOKEN"])
        self.assertIn("gh release", release_step["run"])
        self.assertNotIn("steps.release-tag-token.outputs.token", release_step["run"])

        scorecard = load_yaml(WORKFLOWS / "openssf-scorecard.yml")
        scorecard_job = scorecard["jobs"]["scorecard"]
        self.assertNotIn("id-token", scorecard_job["permissions"])
        run_step = next(
            step for step in scorecard_job["steps"] if step.get("name") == "Run immutable OpenSSF Scorecard analysis"
        )
        self.assertEqual(
            "docker://ghcr.io/ossf/scorecard-action:v2.4.3@sha256:"
            "2dd6a6d60100f78ef24e14a47941d0087a524b4d3642041558239b1c6097c941",
            run_step["uses"],
        )
        self.assertIs(run_step["with"]["publish_results"], False)
        scorecard_action = load_yaml(SCORECARD_ACTION)
        self.assertRegex(scorecard_action["runs"]["image"], PINNED_DOCKER_USE)
        self.assertEqual(
            "${{ github.token }}",
            scorecard_action["inputs"]["repo_token"]["default"],
        )
        self.assertEqual(
            "false",
            scorecard_action["inputs"]["publish_results"]["default"],
        )

    def test_release_automation_uses_the_organization_app(self) -> None:
        for name in (
            "promote-develop-to-main.yml",
            "release-back-sync.yml",
            "release-prepare.yml",
        ):
            with self.subTest(workflow=name):
                text = (WORKFLOWS / name).read_text(encoding="utf-8")
                self.assertIn(
                    "actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1",
                    text,
                )
                self.assertIn("RELEASE_AUTOMATION_APP_CLIENT_ID", text)
                self.assertIn("RELEASE_AUTOMATION_APP_PRIVATE_KEY", text)
                self.assertIn("repositories: ${{ github.event.repository.name }}", text)
                self.assertIn("permission-pull-requests: write", text)
                self.assertNotIn("LITRELEASEBOT_TOKEN", text)
                self.assertNotIn("litreleasebot", text)

        for name in ("release-back-sync.yml", "release-prepare.yml"):
            with self.subTest(identity_workflow=name):
                text = (WORKFLOWS / name).read_text(encoding="utf-8")
                self.assertIn("steps.release-bot.outputs.login", text)
                self.assertIn("steps.release-bot.outputs.email", text)

        back_sync = (WORKFLOWS / "release-back-sync.yml").read_text(encoding="utf-8")
        self.assertIn('"--force-with-lease=${branch_ref}:${remote_branch_sha}"', back_sync)
        self.assertNotIn("authenticated_push --force origin", back_sync)
        release_prepare = (WORKFLOWS / "release-prepare.yml").read_text(encoding="utf-8")
        self.assertIn(
            '"--force-with-lease=${release_ref}:${remote_release_sha}"',
            release_prepare,
        )

    def test_release_evidence_and_publication_are_attempt_and_identity_bound(self) -> None:
        ci = (WORKFLOWS / "collection-ci.yml").read_text(encoding="utf-8")
        self.assertIn("/${GITHUB_RUN_ID}/attempt-${GITHUB_RUN_ATTEMPT}", ci)
        self.assertIn("detect-secrets scan --all-files", ci)
        self.assertIn('detect-secrets scan --all-files "$candidate_extract"', ci)
        self.assertNotIn("detect-secrets scan --all-files \\\n            artifacts/aggregate-input", ci)
        self.assertIn("secret-scan-inventory.json", ci)
        self.assertIn("scripts/enrich-cyclonedx-sbom.py", ci)
        self.assertIn('scripts/source_dependencies.py --candidate "$candidate"', ci)
        self.assertIn('git show "$SOURCE_SHA:meta/source-dependencies.yml"', ci)
        self.assertIn("artifacts/evidence/security/source-dependencies.yml", ci)
        self.assertIn("cmp --silent", ci)

        publish = (WORKFLOWS / "collection-publish.yml").read_text(encoding="utf-8")
        self.assertIn("dist/release/SHA256SUMS.sigstore.json", publish)
        self.assertIn("existing-release-checksum-pair", publish)
        self.assertIn('test "$checksum_asset_count" -eq "$bundle_asset_count"', publish)
        self.assertIn('cmp --silent "$existing_pair/SHA256SUMS"', publish)
        self.assertIn("collection-publish.yml@refs/heads/main", publish)
        self.assertIn('--certificate-github-workflow-sha "$RELEASE_SHA"', publish)
        self.assertIn("cosign verify-blob", publish)

        self.assertIn('--certificate-github-workflow-sha "$SOURCE_SHA"', ci)

        back_sync = (WORKFLOWS / "release-back-sync.yml").read_text(encoding="utf-8")
        self.assertIn("git cat-file -t FETCH_HEAD", back_sync)
        self.assertIn("/apps/${tagger_app_slug}", back_sync)
        self.assertIn("/users/${tagger_app_slug}[bot]", back_sync)
        self.assertIn("EXPECTED_TAG_APP_ID", back_sync)
        self.assertIn("EXPECTED_TAG_APP_CLIENT_ID", back_sync)
        self.assertIn("[A-Za-z0-9._-]{0,127}", back_sync)
        self.assertIn('test "$tagger_app_slug" = "$EXPECTED_TAG_APP_SLUG"', back_sync)
        self.assertNotIn("tagger litreleasebot", back_sync)
        self.assertIn('git merge --no-ff -X ours "$release_sha"', back_sync)
        self.assertIn('test "$tag" = "v${tagged_version}"', back_sync)
        self.assertNotIn("git merge --no-ff -X ours origin/main", back_sync)

        for name in (
            "promote-develop-to-main.yml",
            "release-back-sync.yml",
            "release-prepare.yml",
        ):
            with self.subTest(workflow=name):
                workflow = (WORKFLOWS / name).read_text(encoding="utf-8")
                self.assertIn("GITHUB_REPOSITORY_OWNER", workflow)
                self.assertIn(".head.repo.full_name", workflow)
                self.assertNotIn("gh pr list", workflow)

    def test_release_version_and_merge_policy_fail_closed(self) -> None:
        prepare = (WORKFLOWS / "release-prepare.yml").read_text(encoding="utf-8")
        self.assertIn("scripts/release-version.py", prepare)
        self.assertIn("--write-preparation-receipt changelogs/release-preparation.json", prepare)
        self.assertIn('--base-sha "$BASE_SHA"', prepare)
        self.assertNotIn("AUTO_RELEASE_BUMP", prepare)
        self.assertIn("Required merge method: \\`merge commit\\`", prepare)
        self.assertIn("Immutable tag v${VERSION} already exists", prepare)
        publish = (WORKFLOWS / "collection-publish.yml").read_text(encoding="utf-8")
        self.assertIn("Re-prove fragment-derived version and authorized preparation", publish)
        self.assertIn('test "${#preparation_parents[@]}" -eq 1', publish)
        self.assertIn(
            'git diff --quiet "$REVIEWED_HEAD_SHA" "$RELEASE_SHA" -- .',
            publish,
        )
        self.assertIn("--verify-preparation-receipt", publish)
        self.assertIn("actions/runs/${preparation_run_id}", publish)
        self.assertIn('.conclusion == "success"', publish)
        action = ACTION.read_text(encoding="utf-8")
        collection_ci = (WORKFLOWS / "collection-ci.yml").read_text(encoding="utf-8")
        self.assertIn("QUALITY_SOURCE_SHA:", collection_ci)
        expected_quality_source = (
            "QUALITY_SOURCE_SHA: ${{ github.event_name == 'pull_request' && "
            "github.event.pull_request.head.sha || github.sha }}"
        )
        self.assertIn(
            expected_quality_source,
            collection_ci,
        )
        collection_payload = load_yaml(WORKFLOWS / "collection-ci.yml")
        self.assertNotIn("QUALITY_SOURCE_SHA", collection_payload["env"])
        self.assertNotIn("actions/setup-python@", action)
        self.assertIn('tool_root="$(mktemp -d ', action)
        self.assertIn('echo "QUALITY_TOOL_ROOT=$tool_root" >> "$GITHUB_ENV"', action)
        self.assertIn('python3 -m venv "$tool_root"', action)
        self.assertNotIn("--system-site-packages", action)
        self.assertIn('case "$QUALITY_TOOL_ROOT" in', action)
        self.assertIn('"$RUNNER_TEMP"/supplementary-quality-tools/*)', action)
        self.assertIn('rm -rf -- "$QUALITY_TOOL_ROOT"', action)
        self.assertIn("ansible-core==2.18.18", action)
        self.assertIn("molecule==25.12.0", action)
        self.assertIn("molecule-plugins==25.8.12", action)
        self.assertNotIn("QUALITY_DEFAULT_COLLECTION_PATHS", action)
        self.assertIn('export PATH="$tool_root/bin:$PATH"', action)
        self.assertIn("command -v python3", action)
        self.assertNotRegex(action, r"(?m)(?<![A-Za-z0-9_-])python(?!3)(?:\s|$)")
        self.assertIn(
            "MOLECULE_EPHEMERAL_DIRECTORY=$molecule_ephemeral_root",
            action,
        )
        self.assertIn('molecule_ephemeral_root="${temp_root}/molecule-ephemeral"', action)
        self.assertIn('os.environ["QUALITY_PROFILE"].replace("_", "-")', action)
        self.assertIn('["git", "show", f"{source_sha}:{path.as_posix()}"]', action)
        self.assertIn('registry = Path("meta/role-coverage.yml")', action)
        self.assertIn('"schema_version": 2', action)
        self.assertIn('"test_application_policy": policy', action)
        self.assertIn("scenario-owned test-application descriptors are forbidden", action)

    def test_local_container_launchers_fail_closed_and_guard_ssh_credentials(self) -> None:
        for name in ("wunder-container-run.sh", "wunder-devtools-ee.sh"):
            with self.subTest(wrapper=name):
                wrapper = (ROOT / "scripts" / name).read_text(encoding="utf-8")
                self.assertIn("fail_closed", wrapper)
                self.assertNotIn("fail_or_skip", wrapper)
                self.assertNotIn("skipping local hook", wrapper)

        devtools = (ROOT / "scripts" / "wunder-devtools-ee.sh").read_text(encoding="utf-8")
        self.assertIn(
            'VAGRANT_SSH_POLICY="${WUNDER_DEVTOOLS_FORWARD_VAGRANT_SSH:-disabled}"',
            devtools,
        )
        self.assertNotIn("${VAGRANT_SSH_KEY:+-e VAGRANT_SSH_KEY}", devtools)
        self.assertIn('if [ "$VAGRANT_SSH_POLICY" = enabled ]', devtools)
        self.assertIn(
            'HOME_TMPFS_MOUNT="${CONTAINER_HOME}:rw,exec,nosuid,nodev,size=1g,mode=1777"',
            devtools,
        )
        contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        self.assertIn("explicitly mounted `exec`", contributing)
        self.assertIn("No persistent whole-home cache is mounted", contributing)

        molecule = (ROOT / "scripts" / "devtools-molecule.sh").read_text(encoding="utf-8")
        self.assertIn("Docker is required for Molecule tests", molecule)
        self.assertNotIn("Skipping Molecule tests because Docker", molecule)
        self.assertIn("WUNDER_DEVTOOLS_ROOTFS_MODE=rw", molecule)
        self.assertIn("WUNDER_DEVTOOLS_WORKSPACE_MODE=rw", molecule)
        self.assertIn("WUNDER_DEVTOOLS_RUN_AS_HOST_UID=0", molecule)
        self.assertNotIn("WUNDER_DEVTOOLS_RUN_AS_HOST_UID=1", molecule)

    def test_devtools_capability_policy_expands_to_individual_docker_arguments(self) -> None:
        wrapper = ROOT / "scripts" / "wunder-devtools-ee.sh"
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            fake_bin = temporary / "bin"
            fake_bin.mkdir()
            fake_docker = fake_bin / "docker"
            fake_docker.write_text(
                '#!/usr/bin/env bash\nset -euo pipefail\nprintf "%s\\n" "$@" >"${WUNDER_DEVTOOLS_ARGV:?}"\n',
                encoding="utf-8",
            )
            fake_docker.chmod(0o700)
            captured_arguments = temporary / "docker-arguments"
            container_home = temporary / "container-home"
            environment = os.environ.copy()
            environment.update(
                {
                    "CONTAINER_HOME": str(container_home),
                    "PATH": f"{fake_bin}:{environment['PATH']}",
                    "WUNDER_CONTAINER_ENGINE": "docker",
                    "WUNDER_DEVTOOLS_ARGV": str(captured_arguments),
                    "WUNDER_DEVTOOLS_CAP_ADD": "CHOWN,FOWNER",
                    "WUNDER_DEVTOOLS_DOCKER_SOCKET": "disabled",
                }
            )

            subprocess.run(  # noqa: S603 -- execute the repository-owned wrapper under test.
                ["/usr/bin/bash", str(wrapper), "true"],
                cwd=ROOT,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )

            arguments = captured_arguments.read_text(encoding="utf-8").splitlines()
            capability_indices = [index for index, argument in enumerate(arguments) if argument == "--cap-add"]
            self.assertEqual(["CHOWN", "FOWNER"], [arguments[index + 1] for index in capability_indices])
            self.assertNotIn("CHOWN,FOWNER", arguments)
            capability_drop_index = arguments.index("--cap-drop")
            self.assertEqual("ALL", arguments[capability_drop_index + 1])
            self.assertNotIn("--privileged", arguments)
            self.assertIn(
                f"{container_home}:rw,exec,nosuid,nodev,size=1g,mode=1777",
                arguments,
            )


if __name__ == "__main__":
    unittest.main()
