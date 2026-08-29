"""Build the sanitized final summary for an AtlasRetail deployment canary."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

EXPECTED_MANAGED_RESOURCE_COUNT = 40
EXPECTED_READ_ONLY_DATA_SOURCES = {"aws_iam_policy_document": 6}
SOURCE_COMMIT_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
RUN_ID_PATTERN = re.compile(r"^[0-9]+$")

ERROR_CODES = {
    "admission_verified": "PREREQUISITE_ADMISSION_NOT_VERIFIED",
    "admission_source_bound": "PREREQUISITE_SOURCE_MISMATCH",
    "deployment_verified": "DEPLOYMENT_NOT_VERIFIED",
    "upstream_claim_valid": "UPSTREAM_CLAIM_INVALID",
    "zero_workload_verified": "ZERO_WORKLOAD_NOT_VERIFIED",
    "deployment_resource_count_exact": "DEPLOYMENT_RESOURCE_COUNT_MISMATCH",
    "apply_plan_verified": "APPLY_PLAN_NOT_VERIFIED",
    "apply_plan_mode_valid": "APPLY_PLAN_MODE_INVALID",
    "apply_exact_envelope": "APPLY_EXACT_ENVELOPE_NOT_VERIFIED",
    "apply_resource_count_exact": "APPLY_RESOURCE_COUNT_MISMATCH",
    "apply_data_sources_exact": "APPLY_DATA_SOURCE_COUNT_MISMATCH",
    "destroy_plan_verified": "DESTROY_PLAN_NOT_VERIFIED",
    "destroy_plan_mode_valid": "DESTROY_PLAN_MODE_INVALID",
    "destroy_exact_envelope": "DESTROY_EXACT_ENVELOPE_NOT_VERIFIED",
    "destroy_resource_count_exact": "DESTROY_RESOURCE_COUNT_MISMATCH",
    "teardown_verified": "TEARDOWN_NOT_VERIFIED",
    "source_commit_valid": "SOURCE_COMMIT_INVALID",
    "github_run_id_valid": "GITHUB_RUN_ID_INVALID",
    "session_boundaries_valid": "SESSION_BOUNDARY_INVALID",
    "source_identities_valid": "DEPLOYMENT_SOURCE_IDENTITY_INVALID",
    "budget_envelope_valid": "BUDGET_ENVELOPE_NOT_VERIFIED",
    "runtime_timeline_valid": "RUNTIME_TIMELINE_INVALID",
    "teardown_authority_valid": "TEARDOWN_AUTHORITY_INVALID",
}

WORKLOAD_ACTIONS = {
    "athena:StartQueryExecution",
    "glue:StartJobRun",
    "lambda:InvokeFunction",
    "states:StartExecution",
}


def read_json(path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def valid_run_id(value: str) -> bool:
    return RUN_ID_PATTERN.fullmatch(value) is not None and int(value) > 0


def denies_workload(policy: dict[str, Any]) -> bool:
    return any(
        item.get("Effect") == "Deny"
        and set(item.get("Action", [])) == WORKLOAD_ACTIONS
        and item.get("Resource") == "*"
        for item in policy.get("Statement", [])
        if isinstance(item, dict)
    )


def read_epoch(path: Path) -> int | None:
    try:
        value = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return value if value > 0 else None


def summarize(evidence_directory: Path, source_commit: str, run_id: str) -> dict[str, Any]:
    deployment = read_json(evidence_directory / "deployment-verification.json")
    teardown = read_json(evidence_directory / "teardown.json")
    apply_plan = read_json(evidence_directory / "terraform-apply-plan-validation.json")
    destroy_plan = read_json(evidence_directory / "terraform-destroy-plan-validation.json")
    admission = read_json(evidence_directory / "admission-verification.json")
    deploy_source = read_json(evidence_directory / "deploy-source-identity.json")
    teardown_source = read_json(evidence_directory / "teardown-source-identity.json")
    deploy_policy = read_json(evidence_directory / "deploy-session-policy.json")
    teardown_policy = read_json(evidence_directory / "teardown-session-policy.json")
    teardown_authority = read_json(evidence_directory / "teardown-authority-verification.json")
    budgets = [
        read_json(evidence_directory / name)
        for name in (
            "budget-before-verification.json",
            "budget-after-deployment-verification.json",
            "budget-after-teardown-verification.json",
        )
    ]
    epochs = [
        read_epoch(evidence_directory / name)
        for name in (
            "workflow-started-epoch.txt",
            "terraform-apply-started-epoch.txt",
            "terraform-apply-completed-epoch.txt",
            "deployment-evidence-collected-epoch.txt",
            "terraform-destroy-started-epoch.txt",
            "terraform-destroy-completed-epoch.txt",
        )
    ]
    checks = {
        "admission_verified": admission.get("result") == "PASS",
        "admission_source_bound": admission.get("source_commit") == source_commit,
        "deployment_verified": deployment.get("result") == "PASS",
        "upstream_claim_valid": deployment.get("claim") == "AWS_DEPLOYMENT_VERIFIED",
        "zero_workload_verified": deployment.get("zero_workload") == "PASS",
        "deployment_resource_count_exact": deployment.get("terraform_managed_resource_count")
        == EXPECTED_MANAGED_RESOURCE_COUNT,
        "apply_plan_verified": apply_plan.get("result") == "PASS",
        "apply_plan_mode_valid": apply_plan.get("mode") == "apply",
        "apply_exact_envelope": apply_plan.get("exact_envelope") is True,
        "apply_resource_count_exact": apply_plan.get("resource_count")
        == EXPECTED_MANAGED_RESOURCE_COUNT,
        "apply_data_sources_exact": apply_plan.get("read_only_data_source_counts")
        == EXPECTED_READ_ONLY_DATA_SOURCES,
        "destroy_plan_verified": destroy_plan.get("result") == "PASS",
        "destroy_plan_mode_valid": destroy_plan.get("mode") == "destroy",
        "destroy_exact_envelope": destroy_plan.get("exact_envelope") is True,
        "destroy_resource_count_exact": destroy_plan.get("resource_count")
        == EXPECTED_MANAGED_RESOURCE_COUNT,
        "teardown_verified": teardown.get("result") == "PASS",
        "source_commit_valid": SOURCE_COMMIT_PATTERN.fullmatch(source_commit) is not None,
        "github_run_id_valid": valid_run_id(run_id),
        "session_boundaries_valid": denies_workload(deploy_policy)
        and denies_workload(teardown_policy),
        "source_identities_valid": all(
            value.get("result") == "PASS"
            and value.get("source_commit") == source_commit
            and str(value.get("github_run_id")) == run_id
            for value in (deploy_source, teardown_source)
        ),
        "budget_envelope_valid": all(value.get("result") == "PASS" for value in budgets),
        "runtime_timeline_valid": all(value is not None for value in epochs)
        and epochs == sorted(epochs),
        "teardown_authority_valid": teardown_authority.get("result") == "PASS"
        and teardown_authority.get("source_commit") == source_commit
        and str(teardown_authority.get("run_id")) == run_id,
    }
    errors = [ERROR_CODES[name] for name, check_passed in checks.items() if not check_passed]
    passed = not errors
    return {
        "schema_version": "1.2",
        "project": "AtlasRetail",
        "part": "part-3",
        "proof": "zero-workload-controlled-deployment",
        "source_commit": source_commit,
        "github_run_id": run_id,
        "result": "PASS" if passed else "FAIL",
        "claim": "AWS_DEPLOYMENT_VERIFIED" if passed else "NONE",
        "deployment": "PASS" if checks["deployment_verified"] else "FAIL",
        "readiness": deployment.get("result", "MISSING"),
        "zero_workload": deployment.get("zero_workload", "MISSING"),
        "apply_plan": apply_plan.get("result", "MISSING"),
        "destroy_plan": destroy_plan.get("result", "MISSING"),
        "teardown": teardown.get("result", "MISSING"),
        "active_residue": 0 if checks["teardown_verified"] else "UNKNOWN",
        "terraform_managed_resource_count": deployment.get("terraform_managed_resource_count", 0),
        "runtime_seconds": (
            epochs[-1] - epochs[0] if checks["runtime_timeline_valid"] else "UNCLAIMED"
        ),
        "cost": {
            "budget_envelope": "PASS" if checks["budget_envelope_valid"] else "FAIL",
            "actual_billed_cost": "UNCLAIMED",
        },
        "checks": checks,
        "errors": errors,
    }


def write_manifest(evidence_directory: Path) -> None:
    entries: list[str] = []
    for path in sorted(evidence_directory.iterdir()):
        if (
            not path.is_file()
            or path.suffix == ".tfplan"
            or path.name
            in {
                "evidence-manifest.sha256",
                "terraform-apply-plan.json",
                "terraform-apply-plan.txt",
                "terraform-destroy-plan.json",
                "terraform-destroy-plan.txt",
                "terraform-outputs.json",
            }
        ):
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append(f"{digest}  {path.name}")
    (evidence_directory / "evidence-manifest.sha256").write_text(
        "\n".join(entries) + "\n", encoding="utf-8"
    )


def main(arguments: list[str]) -> int:
    if len(arguments) != 4:
        print(
            "usage: summarize_deployment_evidence.py EVIDENCE_DIR SOURCE_COMMIT RUN_ID",
            file=sys.stderr,
        )
        return 2
    evidence_directory = Path(arguments[1])
    evidence_directory.mkdir(parents=True, exist_ok=True)
    summary = summarize(evidence_directory, arguments[2], arguments[3])
    (evidence_directory / "part-3-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_manifest(evidence_directory)
    return 0 if summary["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
