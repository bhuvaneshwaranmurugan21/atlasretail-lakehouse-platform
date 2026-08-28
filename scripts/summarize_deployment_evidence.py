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
    "deployment_verified": "DEPLOYMENT_NOT_VERIFIED",
    "upstream_claim_valid": "UPSTREAM_CLAIM_INVALID",
    "zero_workload_verified": "ZERO_WORKLOAD_NOT_VERIFIED",
    "deployment_resource_count_exact": "DEPLOYMENT_RESOURCE_COUNT_MISMATCH",
    "apply_plan_verified": "APPLY_PLAN_NOT_VERIFIED",
    "apply_plan_mode_valid": "APPLY_PLAN_MODE_INVALID",
    "apply_resource_count_exact": "APPLY_RESOURCE_COUNT_MISMATCH",
    "apply_data_sources_exact": "APPLY_DATA_SOURCE_COUNT_MISMATCH",
    "destroy_plan_verified": "DESTROY_PLAN_NOT_VERIFIED",
    "destroy_plan_mode_valid": "DESTROY_PLAN_MODE_INVALID",
    "destroy_resource_count_exact": "DESTROY_RESOURCE_COUNT_MISMATCH",
    "teardown_verified": "TEARDOWN_NOT_VERIFIED",
    "source_commit_valid": "SOURCE_COMMIT_INVALID",
    "github_run_id_valid": "GITHUB_RUN_ID_INVALID",
}


def read_json(path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def valid_run_id(value: str) -> bool:
    return RUN_ID_PATTERN.fullmatch(value) is not None and int(value) > 0


def summarize(evidence_directory: Path, source_commit: str, run_id: str) -> dict[str, Any]:
    deployment = read_json(evidence_directory / "deployment-verification.json")
    teardown = read_json(evidence_directory / "teardown.json")
    apply_plan = read_json(evidence_directory / "terraform-apply-plan-validation.json")
    destroy_plan = read_json(evidence_directory / "terraform-destroy-plan-validation.json")
    checks = {
        "deployment_verified": deployment.get("result") == "PASS",
        "upstream_claim_valid": deployment.get("claim") == "AWS_DEPLOYMENT_VERIFIED",
        "zero_workload_verified": deployment.get("zero_workload") == "PASS",
        "deployment_resource_count_exact": deployment.get("terraform_managed_resource_count")
        == EXPECTED_MANAGED_RESOURCE_COUNT,
        "apply_plan_verified": apply_plan.get("result") == "PASS",
        "apply_plan_mode_valid": apply_plan.get("mode") == "apply",
        "apply_resource_count_exact": apply_plan.get("resource_count")
        == EXPECTED_MANAGED_RESOURCE_COUNT,
        "apply_data_sources_exact": apply_plan.get("read_only_data_source_counts")
        == EXPECTED_READ_ONLY_DATA_SOURCES,
        "destroy_plan_verified": destroy_plan.get("result") == "PASS",
        "destroy_plan_mode_valid": destroy_plan.get("mode") == "destroy",
        "destroy_resource_count_exact": destroy_plan.get("resource_count")
        == EXPECTED_MANAGED_RESOURCE_COUNT,
        "teardown_verified": teardown.get("result") == "PASS",
        "source_commit_valid": SOURCE_COMMIT_PATTERN.fullmatch(source_commit) is not None,
        "github_run_id_valid": valid_run_id(run_id),
    }
    errors = [ERROR_CODES[name] for name, check_passed in checks.items() if not check_passed]
    passed = not errors
    return {
        "schema_version": "1.1",
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
