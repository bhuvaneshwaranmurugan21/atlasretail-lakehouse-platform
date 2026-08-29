#!/usr/bin/env python3
"""Independently remove only resources owned by one Glue definition probe run."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from probe_glue_capability import (
    AwsCallError,
    AwsCli,
    AwsRunner,
    _tags,
    expected_tags,
    resource_names,
    validate_boundary,
    wait_absent,
)


def cleanup(
    aws: AwsRunner,
    *,
    account: str,
    region: str,
    run_id: str,
    source_commit: str,
) -> dict[str, Any]:
    """Delete exact owned residue and prove both resources absent."""
    validate_boundary(account, region, run_id, source_commit)
    names = resource_names(account, region, run_id)
    ownership = expected_tags(run_id)
    evidence: dict[str, Any] = {
        "account": account,
        "completed_at": None,
        "errors": [],
        "glue_job_lookup_result": None,
        "glue_job_runs": None,
        "iam_role_lookup_result": None,
        "region": region,
        "result": "FAIL",
        "run_id": run_id,
        "source_commit": source_commit,
        "started_at": datetime.now(UTC).isoformat(),
    }

    try:
        try:
            job_response = aws.run("glue", "get-job", "--job-name", names["job_name"])
        except AwsCallError as error:
            if "EntityNotFoundException" not in error.stderr:
                raise
            evidence["glue_job_lookup_result"] = "EntityNotFoundException"
        else:
            job = job_response.get("Job")
            if not isinstance(job, dict) or job.get("Name") != names["job_name"]:
                raise ValueError("cleanup received a Glue job outside the exact run boundary")
            tag_response = aws.run("glue", "get-tags", "--resource-arn", names["job_arn"])
            tags = tag_response.get("Tags")
            if not isinstance(tags, dict) or tags != ownership:
                raise ValueError("refusing to delete Glue job with mismatched ownership tags")
            runs_response = aws.run(
                "glue", "get-job-runs", "--job-name", names["job_name"], "--max-results", "1"
            )
            runs = runs_response.get("JobRuns")
            if not isinstance(runs, list):
                raise ValueError("cleanup Glue job-run response did not contain a run list")
            evidence["glue_job_runs"] = len(runs)
            if runs:
                evidence["errors"].append("owned probe job unexpectedly contains an execution")
            aws.run("glue", "delete-job", "--job-name", names["job_name"])
            evidence["glue_job_lookup_result"] = wait_absent(
                aws,
                "glue",
                "get-job",
                "--job-name",
                names["job_name"],
                "EntityNotFoundException",
            )
    except (AwsCallError, KeyError, TypeError, ValueError) as error:
        evidence["errors"].append(f"Glue cleanup failed: {error}")

    try:
        try:
            role_response = aws.run("iam", "get-role", "--role-name", names["role_name"])
        except AwsCallError as error:
            if "NoSuchEntity" not in error.stderr:
                raise
            evidence["iam_role_lookup_result"] = "NoSuchEntity"
        else:
            role = role_response.get("Role")
            if (
                not isinstance(role, dict)
                or role.get("RoleName") != names["role_name"]
                or role.get("Arn") != names["role_arn"]
            ):
                raise ValueError("cleanup received an IAM role outside the exact run boundary")
            tag_response = aws.run("iam", "list-role-tags", "--role-name", names["role_name"])
            if _tags(tag_response.get("Tags")) != ownership:
                raise ValueError("refusing to delete IAM role with mismatched ownership tags")
            inline = aws.run("iam", "list-role-policies", "--role-name", names["role_name"])
            attached = aws.run(
                "iam", "list-attached-role-policies", "--role-name", names["role_name"]
            )
            if inline.get("PolicyNames") != [] or attached.get("AttachedPolicies") != []:
                raise ValueError("refusing to delete probe role with unexpected permissions")
            aws.run("iam", "delete-role", "--role-name", names["role_name"])
            evidence["iam_role_lookup_result"] = wait_absent(
                aws,
                "iam",
                "get-role",
                "--role-name",
                names["role_name"],
                "NoSuchEntity",
            )
    except (AwsCallError, KeyError, TypeError, ValueError) as error:
        evidence["errors"].append(f"IAM cleanup failed: {error}")

    evidence["completed_at"] = datetime.now(UTC).isoformat()
    if (
        evidence["glue_job_lookup_result"] == "EntityNotFoundException"
        and evidence["iam_role_lookup_result"] == "NoSuchEntity"
        and evidence["glue_job_runs"] in {None, 0}
        and not evidence["errors"]
    ):
        evidence["result"] = "PASS"
    return evidence


def main(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(arguments)
    try:
        evidence = cleanup(
            AwsCli(args.region),
            account=args.account,
            region=args.region,
            run_id=args.run_id,
            source_commit=args.source_commit,
        )
    except ValueError as error:
        print(f"Glue cleanup rejected before AWS access: {error}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, sort_keys=True))
    return 0 if evidence["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
