"""Fail closed unless an AtlasRetail saved plan stays inside its resource envelope."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from atlasretail.terraform_envelope import EXPECTED_DATA_ADDRESSES, EXPECTED_MANAGED_ADDRESSES

ALLOWED_MAXIMUMS = {
    "aws_athena_workgroup": 1,
    "aws_cloudwatch_log_group": 3,
    "aws_cloudwatch_metric_alarm": 1,
    "aws_dynamodb_table": 1,
    "aws_glue_catalog_database": 1,
    "aws_glue_job": 1,
    "aws_iam_role": 3,
    "aws_iam_role_policy": 3,
    "aws_kms_alias": 1,
    "aws_kms_key": 1,
    "aws_lambda_function": 1,
    "aws_s3_bucket": 3,
    "aws_s3_bucket_lifecycle_configuration": 3,
    "aws_s3_bucket_ownership_controls": 3,
    "aws_s3_bucket_policy": 3,
    "aws_s3_bucket_public_access_block": 3,
    "aws_s3_bucket_server_side_encryption_configuration": 3,
    "aws_s3_bucket_versioning": 3,
    "aws_s3_object": 1,
    "aws_sfn_state_machine": 1,
}

REQUIRED_APPLY_TYPES = {
    "aws_athena_workgroup",
    "aws_dynamodb_table",
    "aws_glue_catalog_database",
    "aws_glue_job",
    "aws_kms_key",
    "aws_lambda_function",
    "aws_s3_bucket",
    "aws_sfn_state_machine",
}

ALLOWED_READ_ONLY_DATA_TYPES = {"aws_iam_policy_document"}


def valid_empty_destroy_plan(plan: dict[str, Any]) -> bool:
    """Accept Terraform's canonical no-state destroy plan shape."""
    root_module = plan.get("planned_values", {}).get("root_module")
    return (
        plan.get("applyable") is False
        and plan.get("complete") is True
        and plan.get("errored") is False
        and root_module == {}
    )


def validate(
    plan: dict[str, Any],
    mode: str,
    exact_envelope: bool = False,
    allow_partial_destroy: bool = False,
) -> dict[str, Any]:
    """Validate actions and type counts for an apply or destroy plan."""
    expected_action = ["create"] if mode == "apply" else ["delete"]
    changes = plan.get("resource_changes")
    if changes is None and mode == "destroy" and valid_empty_destroy_plan(plan):
        changes = []
    if not isinstance(changes, list):
        return {"result": "FAIL", "errors": ["resource_changes is missing"]}

    errors: list[str] = []
    counts: Counter[str] = Counter()
    data_counts: Counter[str] = Counter()
    managed_addresses: set[str] = set()
    data_addresses: set[str] = set()
    for change in changes:
        if not isinstance(change, dict):
            errors.append("resource change is not an object")
            continue
        resource_type = change.get("type")
        address = str(change.get("address", "unknown"))
        actions = change.get("change", {}).get("actions")
        if change.get("mode") == "data":
            if resource_type not in ALLOWED_READ_ONLY_DATA_TYPES:
                errors.append(f"{address}: unexpected data source type {resource_type!r}")
            elif actions != ["read"]:
                errors.append(f"{address}: data source actions {actions!r} are not ['read']")
            else:
                data_counts[str(resource_type)] += 1
                data_addresses.add(address)
            continue
        if resource_type not in ALLOWED_MAXIMUMS:
            errors.append(f"{address}: unexpected resource type {resource_type!r}")
            continue
        counts[str(resource_type)] += 1
        managed_addresses.add(address)
        if actions != expected_action:
            errors.append(f"{address}: actions {actions!r} are not {expected_action!r}")

    for resource_type, count in sorted(counts.items()):
        maximum = ALLOWED_MAXIMUMS[resource_type]
        if count > maximum:
            errors.append(f"{resource_type}: planned {count}, maximum is {maximum}")

    if mode == "apply":
        missing = sorted(REQUIRED_APPLY_TYPES - counts.keys())
        if missing:
            errors.append(f"required apply resource types are missing: {missing}")

    if exact_envelope:
        missing_managed = sorted(EXPECTED_MANAGED_ADDRESSES - managed_addresses)
        unexpected_managed = sorted(managed_addresses - EXPECTED_MANAGED_ADDRESSES)
        expected_data = EXPECTED_DATA_ADDRESSES if mode == "apply" else set()
        missing_data = sorted(expected_data - data_addresses)
        unexpected_data = sorted(data_addresses - expected_data)
        if missing_managed:
            errors.append(f"exact envelope is missing managed addresses: {missing_managed}")
        if unexpected_managed:
            errors.append(f"exact envelope has unexpected managed addresses: {unexpected_managed}")
        if missing_data:
            errors.append(f"exact envelope is missing data addresses: {missing_data}")
        if unexpected_data:
            errors.append(f"exact envelope has unexpected data addresses: {unexpected_data}")
    elif allow_partial_destroy:
        if mode != "destroy":
            errors.append("partial-destroy recovery is valid only for destroy plans")
        unexpected_managed = sorted(managed_addresses - EXPECTED_MANAGED_ADDRESSES)
        if unexpected_managed:
            errors.append(f"partial destroy has unexpected managed addresses: {unexpected_managed}")
        if data_addresses:
            errors.append(
                f"partial destroy has unexpected data addresses: {sorted(data_addresses)}"
            )

    return {
        "result": "PASS" if not errors else "FAIL",
        "mode": mode,
        "exact_envelope": exact_envelope,
        "partial_destroy_recovery": allow_partial_destroy,
        "resource_count": sum(counts.values()),
        "resource_type_counts": dict(sorted(counts.items())),
        "read_only_data_source_counts": dict(sorted(data_counts.items())),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("apply", "destroy"), required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exact-envelope", action="store_true")
    parser.add_argument("--allow-partial-destroy", action="store_true")
    arguments = parser.parse_args()

    try:
        parsed = json.loads(arguments.plan.read_text(encoding="utf-8"))
        plan = parsed if isinstance(parsed, dict) else {}
        if arguments.exact_envelope and arguments.allow_partial_destroy:
            raise ValueError("exact and partial-destroy envelopes are mutually exclusive")
        result = validate(
            plan,
            arguments.mode,
            arguments.exact_envelope,
            arguments.allow_partial_destroy,
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        result = {"result": "FAIL", "mode": arguments.mode, "errors": [str(error)]}
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
