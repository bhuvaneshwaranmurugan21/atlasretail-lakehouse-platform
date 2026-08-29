#!/usr/bin/env python3
"""Validate the three immutable AWS prerequisites for a Phase 5 deployment."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from validate_terraform_plan import EXPECTED_DATA_ADDRESSES, EXPECTED_MANAGED_ADDRESSES


def load(root: Path, name: str, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads((root / name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"{root.name}/{name}: {error}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{root.name}/{name}: not a JSON object")
        return {}
    return value


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def validate_identity(
    value: dict[str, Any],
    *,
    commit: str,
    run_id: str,
    repository: str,
    ref: str,
    label: str,
    errors: list[str],
) -> None:
    expected = {
        "aws_account_id": "857229544428",
        "aws_region": "ap-southeast-2",
        "github_run_id": run_id,
        "oidc_role_arn": "arn:aws:iam::857229544428:role/AtlasRetailGitHubOidcRole",
        "project": "AtlasRetail",
        "ref": ref,
        "repository": repository,
        "result": "PASS",
        "run_ceiling_usd": 5,
        "schema_version": "1.0",
        "source_commit": commit,
        "terraform_state_key": "atlasretail/main.tfstate",
    }
    require(value == expected, f"{label} source identity mismatch", errors)


def validate(args: argparse.Namespace) -> dict[str, Any]:
    errors: list[str] = []
    require(
        re.fullmatch(r"[0-9a-f]{40}", args.source_commit) is not None,
        "invalid source commit",
        errors,
    )
    for label, run_id in (
        ("preflight", args.preflight_run_id),
        ("glue probe", args.glue_probe_run_id),
        ("plan", args.plan_run_id),
    ):
        require(re.fullmatch(r"[1-9][0-9]*", run_id) is not None, f"invalid {label} run ID", errors)

    preflight_identity = load(args.preflight_dir, "source-identity.json", errors)
    validate_identity(
        preflight_identity,
        commit=args.source_commit,
        run_id=args.preflight_run_id,
        repository=args.repository,
        ref=args.ref,
        label="preflight",
        errors=errors,
    )
    preflight = load(args.preflight_dir, "preflight.json", errors)
    require(preflight.get("result") == "PASS", "preflight did not pass", errors)
    require(
        preflight.get("terraform_state_resources") == [], "preflight state is not empty", errors
    )
    require(preflight.get("unexpected_resources") == [], "preflight found active resources", errors)
    require(preflight.get("errors") == [], "preflight contains errors", errors)

    glue_identity = load(args.glue_probe_dir, "source-identity.json", errors)
    validate_identity(
        glue_identity,
        commit=args.source_commit,
        run_id=args.glue_probe_run_id,
        repository=args.repository,
        ref=args.ref,
        label="Glue probe",
        errors=errors,
    )
    glue_summary = load(args.glue_probe_dir, "phase-4-summary.json", errors)
    require(glue_summary.get("result") == "PASS", "Glue capability probe did not pass", errors)
    require(
        glue_summary.get("claim") == "AWS_GLUE_DEFINITION_CAPABILITY_VERIFIED",
        "Glue capability claim mismatch",
        errors,
    )
    require(
        glue_summary.get("source_commit") == args.source_commit,
        "Glue probe source mismatch",
        errors,
    )
    require(
        str(glue_summary.get("run_id")) == args.glue_probe_run_id, "Glue probe run mismatch", errors
    )
    require(
        glue_summary.get("workload_started") is False,
        "Glue probe workload-start proof is absent",
        errors,
    )
    require(
        glue_summary.get("aws_verified", {}).get("independent_cleanup") is True,
        "Glue probe independent cleanup is absent",
        errors,
    )

    plan_identity = load(args.plan_dir, "source-identity.json", errors)
    validate_identity(
        plan_identity,
        commit=args.source_commit,
        run_id=args.plan_run_id,
        repository=args.repository,
        ref=args.ref,
        label="plan",
        errors=errors,
    )
    plan_summary = load(args.plan_dir, "summary.json", errors)
    plan_validation = load(args.plan_dir, "terraform-plan-validation.json", errors)
    no_change = load(args.plan_dir, "no-change-verification.json", errors)
    require(plan_summary.get("result") == "PASS", "plan summary did not pass", errors)
    require(plan_summary.get("source_commit") == args.source_commit, "plan source mismatch", errors)
    require(str(plan_summary.get("github_run_id")) == args.plan_run_id, "plan run mismatch", errors)
    require(plan_validation.get("result") == "PASS", "plan validation did not pass", errors)
    require(
        plan_validation.get("exact_envelope") is True,
        "plan exact envelope was not enforced",
        errors,
    )
    require(
        plan_validation.get("resource_count") == len(EXPECTED_MANAGED_ADDRESSES),
        "plan managed count mismatch",
        errors,
    )
    require(
        plan_validation.get("read_only_data_source_counts")
        == {"aws_iam_policy_document": len(EXPECTED_DATA_ADDRESSES)},
        "plan data-source count mismatch",
        errors,
    )
    require(no_change.get("result") == "PASS", "plan no-change proof did not pass", errors)

    return {
        "schema_version": "1.0",
        "project": "AtlasRetail",
        "phase": "part-3-phase-5",
        "source_commit": args.source_commit,
        "repository": args.repository,
        "ref": args.ref,
        "prerequisite_runs": {
            "read_only_preflight": args.preflight_run_id,
            "glue_capability_probe": args.glue_probe_run_id,
            "plan_only_proof": args.plan_run_id,
        },
        "result": "PASS" if not errors else "FAIL",
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-dir", type=Path, required=True)
    parser.add_argument("--glue-probe-dir", type=Path, required=True)
    parser.add_argument("--plan-dir", type=Path, required=True)
    parser.add_argument("--preflight-run-id", required=True)
    parser.add_argument("--glue-probe-run-id", required=True)
    parser.add_argument("--plan-run-id", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = validate(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
