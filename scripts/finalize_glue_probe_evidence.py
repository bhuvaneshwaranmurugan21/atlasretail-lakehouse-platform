#!/usr/bin/env python3
"""Fail closed over the complete Phase 4 Glue probe evidence contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from build_glue_probe_session_policy import build_policy

TARGET = json.loads(
    (Path(__file__).resolve().parents[1] / ".github" / "atlas-target.json").read_text(
        encoding="utf-8"
    )
)
RAW_FILES = {
    "caller-identity.json",
    "cleanup-caller-identity.json",
    "cleanup-session-policy.json",
    "cleanup-source-identity.json",
    "cleanup-verification.json",
    "glue-service-probe.json",
    "probe-session-policy.json",
    "source-identity.json",
}


def load_object(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"cannot read {path.name}: {error}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{path.name} is not a JSON object")
        return {}
    return value


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_source(source_commit: str, run_id: str, repository: str, ref: str) -> dict[str, Any]:
    return {
        "aws_account_id": TARGET["aws_account_id"],
        "aws_region": TARGET["aws_region"],
        "github_run_id": run_id,
        "oidc_role_arn": TARGET["oidc_role_arn"],
        "project": "AtlasRetail",
        "ref": ref,
        "repository": repository,
        "result": "PASS",
        "run_ceiling_usd": TARGET["run_ceiling_usd"],
        "schema_version": "1.0",
        "source_commit": source_commit,
        "terraform_state_key": TARGET["terraform_state_key"],
    }


def validate_caller(
    value: dict[str, Any], account: str, session_name: str, label: str, errors: list[str]
) -> None:
    require(value.get("Account") == account, f"{label} account mismatch", errors)
    arn = value.get("Arn")
    expected = rf"arn:aws:sts::{account}:assumed-role/AtlasRetailGitHubOidcRole/{session_name}"
    require(
        isinstance(arn, str) and re.fullmatch(expected, arn) is not None,
        f"{label} ARN mismatch",
        errors,
    )


def finalize(
    evidence_dir: Path,
    *,
    account: str,
    region: str,
    run_id: str,
    source_commit: str,
    repository: str,
    ref: str,
    probe_job_result: str,
    cleanup_job_result: str,
) -> dict[str, Any]:
    errors: list[str] = []
    require(account == TARGET["aws_account_id"], "finalizer account mismatch", errors)
    require(region == TARGET["aws_region"], "finalizer region mismatch", errors)
    require(re.fullmatch(r"[1-9][0-9]*", run_id) is not None, "invalid run ID", errors)
    require(
        re.fullmatch(r"[0-9a-f]{40}", source_commit) is not None, "invalid source commit", errors
    )
    observed_files = {path.name for path in evidence_dir.iterdir() if path.is_file()}
    require(
        observed_files == RAW_FILES, "raw evidence file set differs from the exact contract", errors
    )

    values = {name: load_object(evidence_dir / name, errors) for name in RAW_FILES}
    expected_identity = expected_source(source_commit, run_id, repository, ref)
    require(
        values["source-identity.json"] == expected_identity,
        "probe source identity mismatch",
        errors,
    )
    require(
        values["cleanup-source-identity.json"] == expected_identity,
        "cleanup source identity mismatch",
        errors,
    )
    validate_caller(
        values["caller-identity.json"],
        account,
        f"atlasretail-glue-probe-{run_id}",
        "probe caller",
        errors,
    )
    validate_caller(
        values["cleanup-caller-identity.json"],
        account,
        f"atlasretail-glue-cleanup-{run_id}",
        "cleanup caller",
        errors,
    )
    require(
        values["probe-session-policy.json"] == build_policy(run_id, "probe"),
        "probe session policy mismatch",
        errors,
    )
    require(
        values["cleanup-session-policy.json"] == build_policy(run_id, "cleanup"),
        "cleanup session policy mismatch",
        errors,
    )

    probe = values["glue-service-probe.json"]
    expected_cleanup = {"glue_job": "DELETED_AND_VERIFIED", "iam_role": "DELETED_AND_VERIFIED"}
    require(probe.get("account") == account, "probe account mismatch", errors)
    require(probe.get("region") == region, "probe region mismatch", errors)
    require(probe.get("run_id") == run_id, "probe run ID mismatch", errors)
    require(probe.get("source_commit") == source_commit, "probe source commit mismatch", errors)
    require(
        probe.get("status") == "GLUE_CREATE_JOB_VERIFIED", "probe status is not verified", errors
    )
    require(probe.get("workload_started") is False, "probe claims workload execution", errors)
    require(probe.get("glue_job_runs") == 0, "probe did not prove zero Glue job runs", errors)
    require(
        probe.get("role_inertness")
        == {"exact_identity": True, "glue_only_trust": True, "no_permissions": True},
        "probe role inertness mismatch",
        errors,
    )
    require(
        probe.get("job_definition") == {"exact_configuration": True, "exact_ownership": True},
        "Glue definition verification mismatch",
        errors,
    )
    require(probe.get("cleanup") == expected_cleanup, "probe self-cleanup mismatch", errors)
    require(probe.get("errors") == [], "probe contains errors", errors)

    cleanup = values["cleanup-verification.json"]
    require(cleanup.get("account") == account, "cleanup account mismatch", errors)
    require(cleanup.get("region") == region, "cleanup region mismatch", errors)
    require(cleanup.get("run_id") == run_id, "cleanup run ID mismatch", errors)
    require(cleanup.get("source_commit") == source_commit, "cleanup source commit mismatch", errors)
    require(cleanup.get("result") == "PASS", "independent cleanup failed", errors)
    require(
        cleanup.get("glue_job_lookup_result") == "EntityNotFoundException",
        "Glue job absence is not proven",
        errors,
    )
    require(
        cleanup.get("iam_role_lookup_result") == "NoSuchEntity",
        "IAM role absence is not proven",
        errors,
    )
    require(cleanup.get("glue_job_runs") in {None, 0}, "cleanup observed a Glue job run", errors)
    require(cleanup.get("errors") == [], "cleanup contains errors", errors)
    require(probe_job_result == "success", "probe GitHub job did not succeed", errors)
    require(cleanup_job_result == "success", "cleanup GitHub job did not succeed", errors)

    summary = {
        "account": account,
        "aws_verified": {
            "definition_created_and_read": not errors,
            "independent_cleanup": not errors,
            "oidc_callers": not errors,
            "role_inert": not errors,
            "zero_glue_job_runs": not errors,
        },
        "claim": "AWS_GLUE_DEFINITION_CAPABILITY_VERIFIED" if not errors else "UNCLAIMED",
        "cleanup_job_result": cleanup_job_result,
        "errors": errors,
        "probe_job_result": probe_job_result,
        "region": region,
        "result": "PASS" if not errors else "FAIL",
        "run_id": run_id,
        "source_commit": source_commit,
        "unclaimed": [
            "actual_billed_cost",
            "controlled_deployment",
            "global_account_cleanliness",
            "glue_runtime_execution",
            "current_source_plan_only_proof",
            "spark_runtime_correctness_on_aws",
            "workload_execution",
        ],
        "workload_started": (
            False
            if probe.get("workload_started") is False and probe.get("glue_job_runs") == 0
            else "UNCLAIMED"
        ),
    }
    summary_path = evidence_dir / "phase-4-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_paths = sorted(
        (evidence_dir / name for name in RAW_FILES if (evidence_dir / name).is_file()),
        key=lambda path: path.name,
    )
    manifest_paths.append(summary_path)
    manifest = {
        "files": {path.name: sha256(path) for path in manifest_paths},
        "result": summary["result"],
        "run_id": run_id,
        "source_commit": source_commit,
    }
    (evidence_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--account", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--probe-job-result", required=True)
    parser.add_argument("--cleanup-job-result", required=True)
    args = parser.parse_args()
    summary = finalize(
        args.evidence_dir,
        account=args.account,
        region=args.region,
        run_id=args.run_id,
        source_commit=args.source_commit,
        repository=args.repository,
        ref=args.ref,
        probe_job_result=args.probe_job_result,
        cleanup_job_result=args.cleanup_job_result,
    )
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
