"""Verify the persistent portfolio foundation from captured AWS read APIs."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TARGET = json.loads((ROOT / ".github" / "atlas-target.json").read_text(encoding="utf-8"))


def load(directory: Path, name: str) -> dict[str, Any]:
    value = json.loads((directory / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{name} must contain a JSON object")
    return value


def output_map(stack: dict[str, Any]) -> dict[str, str]:
    stacks = stack.get("Stacks", [])
    first = stacks[0] if isinstance(stacks, list) and stacks else {}
    outputs = first.get("Outputs", []) if isinstance(first, dict) else []
    return {
        str(item.get("OutputKey")): str(item.get("OutputValue"))
        for item in outputs
        if isinstance(item, dict) and item.get("OutputKey") and item.get("OutputValue")
    }


def table_is_hardened(
    table_payload: dict[str, Any],
    backup_payload: dict[str, Any],
    expected_name: str,
    expected_key: str,
) -> bool:
    table = table_payload.get("Table", {})
    backup = backup_payload.get("ContinuousBackupsDescription", {})
    recovery = backup.get("PointInTimeRecoveryDescription", {}) if isinstance(backup, dict) else {}
    billing = table.get("BillingModeSummary", {}) if isinstance(table, dict) else {}
    encryption = table.get("SSEDescription", {}) if isinstance(table, dict) else {}
    keys = table.get("KeySchema", []) if isinstance(table, dict) else []
    attributes = table.get("AttributeDefinitions", []) if isinstance(table, dict) else []
    return bool(
        isinstance(table, dict)
        and table.get("TableName") == expected_name
        and table.get("TableStatus") == "ACTIVE"
        and isinstance(billing, dict)
        and billing.get("BillingMode") == "PAY_PER_REQUEST"
        and isinstance(encryption, dict)
        and encryption.get("Status") == "ENABLED"
        and isinstance(keys, list)
        and keys == [{"AttributeName": expected_key, "KeyType": "HASH"}]
        and attributes == [{"AttributeName": expected_key, "AttributeType": "S"}]
        and isinstance(recovery, dict)
        and recovery.get("PointInTimeRecoveryStatus") == "ENABLED"
    )


def verify(
    directory: Path,
    preflight: dict[str, Any],
    lease_contention: dict[str, Any],
    lease_release: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    stack = load(directory, "stack.json")
    resources = load(directory, "stack-resources.json")
    encryption = load(directory, "bucket-encryption.json")
    versioning = load(directory, "bucket-versioning.json")
    public_access = load(directory, "bucket-public-access.json")
    ownership = load(directory, "bucket-ownership.json")
    bucket_policy = load(directory, "bucket-policy.json")
    lifecycle = load(directory, "bucket-lifecycle.json")
    lock_table = load(directory, "lock-table.json")
    lock_backups = load(directory, "lock-backups.json")
    lease_table = load(directory, "lease-table.json")
    lease_backups = load(directory, "lease-backups.json")
    lease_ttl = load(directory, "lease-ttl.json")
    budget = load(directory, "budget.json")
    notifications = load(directory, "budget-notifications.json")

    stacks = stack.get("Stacks", [])
    first_stack = stacks[0] if isinstance(stacks, list) and stacks else {}
    stack_status = first_stack.get("StackStatus") if isinstance(first_stack, dict) else None
    if stack_status not in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}:
        errors.append("Foundation CloudFormation stack is not complete")

    outputs = output_map(stack)
    expected_outputs = {
        "TerraformStateBucket": TARGET["terraform_state_bucket"],
        "TerraformLockTable": TARGET["terraform_lock_table"],
        "AccountLeaseTable": TARGET["account_lease_table"],
        "BudgetName": TARGET["budget_name"],
    }
    if outputs != expected_outputs:
        errors.append("Foundation stack outputs do not match the checked-in AWS target")

    summaries = resources.get("StackResourceSummaries", [])
    resource_types = sorted(
        str(item.get("ResourceType")) for item in summaries if isinstance(item, dict)
    )
    expected_types = sorted(
        [
            "AWS::Budgets::Budget",
            "AWS::DynamoDB::Table",
            "AWS::DynamoDB::Table",
            "AWS::S3::Bucket",
            "AWS::S3::BucketPolicy",
        ]
    )
    if resource_types != expected_types:
        errors.append("Foundation stack contains unexpected resource types")

    rules = encryption.get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
    algorithms = {
        rule.get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm")
        for rule in rules
        if isinstance(rule, dict)
    }
    if algorithms != {"AES256"}:
        errors.append("Terraform state bucket encryption is not exactly AES256")
    if versioning.get("Status") != "Enabled":
        errors.append("Terraform state bucket versioning is not enabled")
    ownership_rules = ownership.get("OwnershipControls", {}).get("Rules", [])
    if not (
        isinstance(ownership_rules, list)
        and len(ownership_rules) == 1
        and ownership_rules[0].get("ObjectOwnership") == "BucketOwnerEnforced"
    ):
        errors.append("Terraform state bucket ownership is not enforced")

    block = public_access.get("PublicAccessBlockConfiguration", {})
    if not isinstance(block, dict) or not all(
        block.get(key) is True
        for key in (
            "BlockPublicAcls",
            "BlockPublicPolicy",
            "IgnorePublicAcls",
            "RestrictPublicBuckets",
        )
    ):
        errors.append("Terraform state bucket public-access block is incomplete")

    try:
        policy = json.loads(str(bucket_policy.get("Policy", "")))
    except json.JSONDecodeError:
        policy = {}
    statements = policy.get("Statement", []) if isinstance(policy, dict) else []
    bucket_arn = f"arn:aws:s3:::{TARGET['terraform_state_bucket']}"
    tls_deny = False
    for statement in statements if isinstance(statements, list) else []:
        if not isinstance(statement, dict):
            continue
        resources = statement.get("Resource", [])
        resource_set = {resources} if isinstance(resources, str) else set(resources)
        secure_transport = statement.get("Condition", {}).get("Bool", {}).get("aws:SecureTransport")
        if (
            statement.get("Effect") == "Deny"
            and statement.get("Principal") == "*"
            and statement.get("Action") == "s3:*"
            and resource_set == {bucket_arn, f"{bucket_arn}/*"}
            and secure_transport in {False, "false"}
        ):
            tls_deny = True
            break
    if not tls_deny:
        errors.append("Terraform state bucket policy does not deny insecure transport")

    lifecycle_rules = lifecycle.get("Rules", [])
    noncurrent_days = {
        rule.get("NoncurrentVersionExpiration", {}).get("NoncurrentDays")
        for rule in lifecycle_rules
        if isinstance(rule, dict) and rule.get("Status") == "Enabled"
    }
    if 30 not in noncurrent_days:
        errors.append("Terraform state bucket does not expire old versions after 30 days")

    if not table_is_hardened(lock_table, lock_backups, TARGET["terraform_lock_table"], "LockID"):
        errors.append("Terraform lock table is not active, encrypted, on-demand, and PITR-enabled")
    if not table_is_hardened(lease_table, lease_backups, TARGET["account_lease_table"], "lock_id"):
        errors.append("Account lease table is not active, encrypted, on-demand, and PITR-enabled")
    ttl = lease_ttl.get("TimeToLiveDescription", {})
    if not isinstance(ttl, dict) or ttl.get("TimeToLiveStatus") != "ENABLED":
        errors.append("Account lease TTL is not enabled")
    if ttl.get("AttributeName") != "expires_at":
        errors.append("Account lease TTL uses the wrong attribute")

    budget_value = budget.get("Budget", {})
    limit = budget_value.get("BudgetLimit", {}) if isinstance(budget_value, dict) else {}
    try:
        budget_limit = float(limit.get("Amount")) if isinstance(limit, dict) else None
    except (TypeError, ValueError):
        budget_limit = None
    cost_types = budget_value.get("CostTypes", {}) if isinstance(budget_value, dict) else {}
    if not (
        isinstance(budget_value, dict)
        and budget_value.get("BudgetName") == TARGET["budget_name"]
        and budget_value.get("BudgetType") == "COST"
        and budget_value.get("TimeUnit") == "MONTHLY"
        and budget_limit == float(TARGET["monthly_budget_usd"])
        and limit.get("Unit") == "USD"
        and isinstance(cost_types, dict)
        and cost_types.get("IncludeCredit") is False
    ):
        errors.append("Foundation budget is not the exact 20 USD gross-cost guardrail")

    expected_notifications = {
        ("ACTUAL", 50.0, "PERCENTAGE"),
        ("ACTUAL", 80.0, "PERCENTAGE"),
        ("FORECASTED", 100.0, "PERCENTAGE"),
    }
    notification_values = notifications.get("Notifications", [])
    actual_notifications: set[tuple[str, float, str]] = set()
    for item in notification_values if isinstance(notification_values, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            threshold = float(item.get("Threshold"))
        except (TypeError, ValueError):
            continue
        actual_notifications.add(
            (
                str(item.get("NotificationType")),
                threshold,
                str(item.get("ThresholdType", "PERCENTAGE")),
            )
        )
    if actual_notifications != expected_notifications:
        errors.append("Budget notification thresholds are incomplete or unexpected")

    subscriber_files = (
        "budget-subscribers-actual-50.json",
        "budget-subscribers-actual-80.json",
        "budget-subscribers-forecasted-100.json",
    )
    subscriber_counts: dict[str, int] = {}
    for name in subscriber_files:
        subscribers = load(directory, name).get("Subscribers", [])
        count = sum(
            1
            for subscriber in subscribers
            if isinstance(subscriber, dict)
            and subscriber.get("SubscriptionType") == "EMAIL"
            and isinstance(subscriber.get("Address"), str)
            and "@" in subscriber["Address"]
        )
        subscriber_counts[name] = count
        if count < 1:
            errors.append(f"{name} has no valid email subscriber")

    zero_workload_verified = preflight.get("result") == "PASS" and not preflight.get(
        "unexpected_resources"
    )
    if not zero_workload_verified:
        errors.append("AtlasRetail zero-workload preflight did not pass")
    if lease_contention != {"result": "PASS", "contention_blocked": True}:
        errors.append("Account lease contention was not blocked")
    if lease_release != {"result": "PASS", "owner_scoped_release": True}:
        errors.append("Account lease was not released by its owner")

    return {
        "result": "PASS" if not errors else "FAIL",
        "stack_status": stack_status,
        "outputs": outputs,
        "resource_types": resource_types,
        "budget_notification_count": len(actual_notifications),
        "budget_notifications": [
            {
                "notification_type": notification_type,
                "threshold": threshold,
                "threshold_type": threshold_type,
            }
            for notification_type, threshold, threshold_type in sorted(actual_notifications)
        ],
        "email_subscriber_counts": subscriber_counts,
        "zero_workload_verified": zero_workload_verified,
        "lease_contention_blocked": lease_contention.get("contention_blocked") is True,
        "lease_owner_release_verified": lease_release.get("owner_scoped_release") is True,
        "errors": errors,
    }


def main(arguments: list[str]) -> int:
    if len(arguments) != 6:
        print(
            "usage: verify_foundation.py INPUT_DIR PREFLIGHT_JSON CONTENTION_JSON "
            "RELEASE_JSON OUTPUT_JSON",
            file=sys.stderr,
        )
        return 2
    try:
        preflight = json.loads(Path(arguments[2]).read_text(encoding="utf-8"))
        contention = json.loads(Path(arguments[3]).read_text(encoding="utf-8"))
        release = json.loads(Path(arguments[4]).read_text(encoding="utf-8"))
        if not all(isinstance(value, dict) for value in (preflight, contention, release)):
            raise ValueError("verification inputs must contain JSON objects")
        result = verify(Path(arguments[1]), preflight, contention, release)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"foundation evidence is unreadable: {error}", file=sys.stderr)
        return 2
    output = Path(arguments[5])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for error in result["errors"]:
        print(f"foundation verification failed: {error}", file=sys.stderr)
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
