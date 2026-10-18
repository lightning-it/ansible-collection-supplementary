"""Authenticate normal App preparation ingress and its approved Main promotion.

Read-only consumer of the pinned public Required Workflow. No review request,
workflow dispatch, approval, credential mutation or publication is implemented.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import security_main_promotion as git_contract

CONTROL_SOURCE = "bb1a5df9f54c5f98547048297e7e367cc382543e"
APP = ("lightning-it-release-automation[bot]", 307565056, "Bot")
RECEIPT = "changelogs/release-preparation.json"


def require(value, message):
    if not value:
        raise ValueError(message)


def version_module():
    path = Path(__file__).with_name("release-version.py")
    spec = importlib.util.spec_from_file_location("normal_release_version", path)
    require(spec is not None and spec.loader is not None, "release-version-module-unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def text(root, *args):
    return git_contract.git_text(root, *args)


def document(root, revision):
    raw = git_contract.git_bytes(root, "show", f"{revision}:{RECEIPT}")
    value = git_contract.CONTRACT.load_json_bytes(raw, "normal release receipt")
    require(raw == git_contract.CONTRACT.canonical_document_bytes(value), "noncanonical-release-receipt")
    require(
        value.get("schema_version") == 3 and value.get("release_mode") == "normal", "normal-two-stage-schema-required"
    )
    return value


def preparation(root, base, head, workflow_source, repository, repository_id):
    for revision in (base, head, workflow_source):
        require(isinstance(revision, str) and re.fullmatch(r"[0-9a-f]{40}", revision), "invalid-revision")
    receipt = document(root, head)
    version = receipt["next_version"]
    require(receipt["workflow"]["source_sha"] == workflow_source, "preparation-workflow-source-drift")
    version_module().verify_preparation_receipt(
        receipt,
        expected_repository=repository,
        expected_repository_id=repository_id,
        expected_base_sha=base,
        expected_version=version,
        root=root,
    )
    git_contract.require_app_commit(root, base, head, f"chore(release): prepare v{version}")
    require(git_contract.is_ancestor(root, workflow_source, base), "workflow-source-not-in-content-ancestry")
    changes = dict((path, status) for status, path in git_contract.changed_paths(root, base, head))
    fragments = {f"changelogs/fragments/{item['path']}" for item in receipt["fragments"]}
    require({RECEIPT, "galaxy.yml"} <= changes.keys(), "release-generated-state-missing")
    require(set(changes) <= git_contract.RELEASE_GENERATED_PATHS | fragments, "non-generated-release-path")
    require(all(changes.get(path) == "D" for path in fragments), "reviewed-fragment-not-consumed")
    require(all(status in {"A", "M", "D"} for status in changes.values()), "release-path-type-change")
    for item in receipt["fragments"]:
        raw = git_contract.git_bytes(root, "show", f"{base}:changelogs/fragments/{item['path']}")
        require(git_contract.CONTRACT.sha256_bytes(raw) == f"sha256:{item['sha256']}", "fragment-digest-drift")
    for revision, expected in (
        (base, receipt["current_version"]),
        (workflow_source, receipt["current_version"]),
        (head, version),
    ):
        raw = git_contract.git_bytes(root, "show", f"{revision}:galaxy.yml").decode()
        observed = re.findall(r"(?m)^version:\s*[\"']?([^\s\"']+)[\"']?\s*$", raw)
        require(observed == [expected], "release-version-drift")
    return receipt


def merged_pull(api, repository, merge, base_ref, head_ref, base, head):
    matches = [
        p
        for p in api.pages(f"repos/{repository}/commits/{merge}/pulls")
        if p.get("merged_at") and p.get("merge_commit_sha") == merge and p.get("base", {}).get("ref") == base_ref
    ]
    require(len(matches) == 1, "unique-merged-release-pr-required")
    pull = api.call(f"repos/{repository}/pulls/{matches[0]['number']}")
    require(
        pull.get("merged") is True
        and pull.get("state") == "closed"
        and pull.get("draft") is False
        and pull.get("merged_at")
        and pull.get("merge_commit_sha") == merge,
        "merged-release-pr-drift",
    )
    require(tuple(pull.get("user", {}).get(k) for k in ("login", "id", "type")) == APP, "release-app-pr-required")
    require(
        pull.get("base", {}).get("repo", {}).get("full_name") == repository
        and pull.get("head", {}).get("repo", {}).get("full_name") == repository,
        "same-repository-release-pr-required",
    )
    require(
        pull["base"]["ref"] == base_ref
        and pull["head"]["ref"] == head_ref
        and pull["base"]["sha"] == base
        and pull["head"]["sha"] == head,
        "exact-release-pr-relationship-required",
    )
    return pull


def load_control(directory):
    require(text(directory, "rev-parse", "HEAD") == CONTROL_SOURCE, "pinned-control-source-required")
    require(not text(directory, "status", "--porcelain"), "clean-control-source-required")
    sys.path.insert(0, str(directory / "scripts"))
    return importlib.import_module("workflow_control")


def promotion_control(api, core, repository, pull, config):
    runs = api.pages(f"repos/{repository}/actions/runs?head_sha={pull['head']['sha']}", "workflow_runs")
    cache = {}
    candidates = core.ingress_candidates(api, repository, pull, config["accepted_sources"], runs, cache)
    require(candidates, "native-promotion-run-required")
    observed = max(candidates, key=lambda run: (run["id"], run["run_attempt"]))
    selected = observed
    excluded = []
    if observed["status"] != "completed" or observed["conclusion"] != "success":
        # Reuse the source's exact historical closure-only proof. Semantic
        # failures, drift, pending and failed reviews never gain an exception.
        from workflow_ingress import merged_attempt

        selected, excluded = merged_attempt(api, repository, pull, observed)
    gates = [j for j in core.native_jobs(api, repository, selected) if j.get("name") == "Current revision review"]
    require(len(gates) == 1 and gates[0].get("conclusion") == "success", "native-promotion-gate-required")
    proof = core.artifact_record(
        api, repository, selected, f"control-proof-{selected['run_attempt']}", "control-proof.json"
    )
    require(
        proof.get("version") == 1
        and proof.get("source_sha") in config["accepted_sources"]
        and proof.get("binding") == core.binding(pull)
        and proof.get("route") == "promotion",
        "native-promotion-proof-binding",
    )
    authorization = proof.get("authorization")
    require(
        type(authorization) is dict and type(authorization.get("run")) is int and authorization["run"] > 0,
        "native-promotion-approval-required",
    )
    approval_run = api.call(f"repos/{repository}/actions/runs/{authorization['run']}")
    require(
        core.native_required(approval_run, repository) and approval_run.get("head_sha") == pull["head"]["sha"],
        "native-approval-run-origin",
    )
    operation = core.operation_record(api, repository, approval_run, proof["source_sha"])
    require(
        core.same_immutable_tuple(operation.get("binding", {}), core.binding(pull)), "native-approval-operation-drift"
    )
    core.normal_environment(api, repository)
    require(
        core.native_approval(api, repository, authorization["run"]) == authorization.get("approval"),
        "native-human-approval-drift",
    )
    current = api.call(f"repos/{repository}/actions/runs/{observed['id']}")
    require(
        all(
            current.get(k) == observed.get(k)
            for k in ("id", "run_attempt", "head_sha", "status", "conclusion", "workflow_id", "workflow_url", "path")
        ),
        "native-promotion-generation-drift",
    )
    latest = api.pages(f"repos/{repository}/actions/runs?head_sha={pull['head']['sha']}", "workflow_runs")
    candidates = core.ingress_candidates(api, repository, pull, config["accepted_sources"], latest, cache)
    require(
        candidates
        and max((r["id"], r["run_attempt"]) for r in candidates) == (observed["id"], observed["run_attempt"]),
        "newer-promotion-generation",
    )
    return proof, excluded


def control_reference(value):
    keys = {"run", "attempt", "job", "head", "source_sha", "route", "artifact", "proof_sha256"}
    require(
        type(value) is dict and keys <= value.keys() and set(value) <= keys | {"post_merge_failed_attempts"},
        "native-control-reference-shape",
    )
    return {key: value[key] for key in keys}


def publish(root, api, core, repository, repository_id, release, base, head):
    require(text(root, "rev-parse", "HEAD") == release, "exact-release-checkout-required")
    receipt = document(root, release)
    require(
        receipt["repository"] == repository and receipt["repository_id"] == repository_id,
        "release-repository-identity-drift",
    )
    require(
        text(root, "show", "-s", "--format=%P", release).split() == [base, head],
        "exact-promotion-merge-parents-required",
    )
    require(
        text(root, "rev-parse", f"{release}^{{tree}}") == text(root, "rev-parse", f"{head}^{{tree}}"),
        "promotion-tree-drift",
    )
    content_base = receipt["content_base"]["sha"]
    ingress_parents = text(root, "show", "-s", "--format=%P", head).split()
    require(
        len(ingress_parents) == 2 and ingress_parents[0] == content_base, "exact-preparation-ingress-parents-required"
    )
    prepared = ingress_parents[1]
    require(
        text(root, "rev-parse", f"{head}^{{tree}}") == text(root, "rev-parse", f"{prepared}^{{tree}}"),
        "preparation-ingress-tree-drift",
    )
    workflow_source = receipt["workflow"]["source_sha"]
    require(
        git_contract.is_ancestor(root, workflow_source, base) and git_contract.is_ancestor(root, base, content_base),
        "protected-main-ancestry-required",
    )
    require(
        preparation(root, content_base, prepared, workflow_source, repository, repository_id) == receipt,
        "preparation-receipt-drift",
    )
    prep = merged_pull(api, repository, head, "develop", f"release/v{receipt['next_version']}", content_base, prepared)
    promotion = merged_pull(api, repository, release, "main", "develop", base, head)
    config = core.policy(api, repository, base, CONTROL_SOURCE)
    ingress = core.check_native_control(api, repository, prep, config)
    require(ingress["route"] == "codex", "genuine-app-ingress-review-required")
    proof, excluded = promotion_control(api, core, repository, promotion, config)
    evidence = proof.get("evidence", {})
    require(
        evidence.get("base") == base
        and evidence.get("head") == head
        and evidence.get("integration_tree") == text(root, "rev-parse", f"{release}^{{tree}}"),
        "native-promotion-integration-tree-drift",
    )
    references = [
        item for item in evidence.get("ingress", []) if item.get("pull") == prep["number"] and item.get("merge") == head
    ]
    require(
        len(references) == 1 and control_reference(references[0].get("control")) == control_reference(ingress),
        "preparation-not-in-native-promotion-coverage",
    )
    workflow = receipt["workflow"]
    run = api.call(f"repos/{repository}/actions/runs/{workflow['run_id']}")
    require(
        str(run.get("id")) == workflow["run_id"]
        and str(run.get("run_attempt")) == workflow["run_attempt"]
        and run.get("repository", {}).get("full_name") == repository
        and run.get("head_repository", {}).get("full_name") == repository
        and run.get("head_sha") == workflow_source
        and run.get("head_branch") == "main"
        and run.get("path") == workflow["path"]
        and run.get("event") == workflow["event"]
        and run.get("actor", {}).get("login") == workflow["actor"]
        and run.get("status") == "completed"
        and run.get("conclusion") == "success",
        "protected-main-preparation-run-required",
    )
    require(api.call(f"repos/{repository}/git/ref/heads/main")["object"]["sha"] == release, "protected-main-tip-drift")
    for pull in (prep, promotion):
        current = api.call(f"repos/{repository}/pulls/{pull['number']}")
        require(
            core.binding(current) == core.binding(pull)
            and all(current.get(key) == pull.get(key) for key in ("state", "merged", "merged_at", "merge_commit_sha")),
            "release-pull-changed",
        )
    return {
        "content_base": content_base,
        "prepared_head": prepared,
        "develop_merge": head,
        "main_merge": release,
        "preparation_pr": prep["number"],
        "promotion_pr": promotion["number"],
        "promotion_proof_sha256": core.digest(proof),
        "post_merge_failed_attempts": excluded,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("preparation", "publish"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--workflow-source")
    parser.add_argument("--release")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--control-root", type=Path)
    args = parser.parse_args()
    try:
        if args.operation == "preparation":
            result = preparation(
                args.root, args.base, args.head, args.workflow_source, args.repository, args.repository_id
            )
        else:
            core = load_control(args.control_root)
            result = publish(
                args.root, core.API(), core, args.repository, args.repository_id, args.release, args.base, args.head
            )
    except (ValueError, git_contract.PromotionError, git_contract.CONTRACT.ContractError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
