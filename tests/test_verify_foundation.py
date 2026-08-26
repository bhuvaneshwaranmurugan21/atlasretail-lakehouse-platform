from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_foundation.py"
SPEC = importlib.util.spec_from_file_location("verify_foundation", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write(directory: Path, name: str, value: object) -> None:
    (directory / name).write_text(json.dumps(value), encoding="utf-8")


def table(name: str, key: str) -> dict[str, object]:
    return {
        "Table": {
            "TableName": name,
            "TableStatus": "ACTIVE",
            "BillingModeSummary": {"BillingMode": "PAY_PER_REQUEST"},
            "SSEDescription": {"Status": "ENABLED"},
            "KeySchema": [{"AttributeName": key, "KeyType": "HASH"}],
            "AttributeDefinitions": [{"AttributeName": key, "AttributeType": "S"}],
        }
    }


def populate(directory: Path) -> None:
    target = MODULE.TARGET
    write(
        directory,
        "stack.json",
        {
            "Stacks": [
                {
                    "StackStatus": "CREATE_COMPLETE",
                    "Outputs": [
                        {
                            "OutputKey": "TerraformStateBucket",
                            "OutputValue": target["terraform_state_bucket"],
                        },
                        {
                            "OutputKey": "TerraformLockTable",
                            "OutputValue": target["terraform_lock_table"],
                        },
                        {
                            "OutputKey": "AccountLeaseTable",
                            "OutputValue": target["account_lease_table"],
                        },
                        {"OutputKey": "BudgetName", "OutputValue": target["budget_name"]},
                    ],
                }
            ]
        },
    )
    write(
        directory,
        "stack-resources.json",
        {
            "StackResourceSummaries": [
                {"ResourceType": "AWS::S3::Bucket"},
                {"ResourceType": "AWS::S3::BucketPolicy"},
                {"ResourceType": "AWS::DynamoDB::Table"},
                {"ResourceType": "AWS::DynamoDB::Table"},
                {"ResourceType": "AWS::Budgets::Budget"},
            ]
        },
    )
    write(
        directory,
        "bucket-encryption.json",
        {
            "ServerSideEncryptionConfiguration": {
                "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
            }
        },
    )
    write(directory, "bucket-versioning.json", {"Status": "Enabled"})
    write(
        directory,
        "bucket-ownership.json",
        {"OwnershipControls": {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]}},
    )
    write(
        directory,
        "bucket-public-access.json",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            }
        },
    )
    write(
        directory,
        "bucket-policy.json",
        {
            "Policy": json.dumps(
                {
                    "Statement": [
                        {
                            "Effect": "Deny",
                            "Principal": "*",
                            "Action": "s3:*",
                            "Resource": [
                                f"arn:aws:s3:::{MODULE.TARGET['terraform_state_bucket']}",
                                f"arn:aws:s3:::{MODULE.TARGET['terraform_state_bucket']}/*",
                            ],
                            "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                        }
                    ]
                }
            )
        },
    )
    write(
        directory,
        "bucket-lifecycle.json",
        {
            "Rules": [
                {
                    "Status": "Enabled",
                    "NoncurrentVersionExpiration": {"NoncurrentDays": 30},
                }
            ]
        },
    )
    write(directory, "lock-table.json", table(target["terraform_lock_table"], "LockID"))
    write(directory, "lease-table.json", table(target["account_lease_table"], "lock_id"))
    backups = {
        "ContinuousBackupsDescription": {
            "PointInTimeRecoveryDescription": {"PointInTimeRecoveryStatus": "ENABLED"}
        }
    }
    write(directory, "lock-backups.json", backups)
    write(directory, "lease-backups.json", backups)
    write(
        directory,
        "lease-ttl.json",
        {"TimeToLiveDescription": {"TimeToLiveStatus": "ENABLED", "AttributeName": "expires_at"}},
    )
    write(
        directory,
        "budget.json",
        {
            "Budget": {
                "BudgetName": target["budget_name"],
                "BudgetType": "COST",
                "TimeUnit": "MONTHLY",
                "BudgetLimit": {"Amount": "20", "Unit": "USD"},
                "CostTypes": {"IncludeCredit": False},
            }
        },
    )
    write(
        directory,
        "budget-notifications.json",
        {
            "Notifications": [
                {"NotificationType": "ACTUAL", "Threshold": 50, "ThresholdType": "PERCENTAGE"},
                {"NotificationType": "ACTUAL", "Threshold": 80, "ThresholdType": "PERCENTAGE"},
                {
                    "NotificationType": "FORECASTED",
                    "Threshold": 100,
                    "ThresholdType": "PERCENTAGE",
                },
            ]
        },
    )
    subscriber = {"Subscribers": [{"SubscriptionType": "EMAIL", "Address": "owner@example.com"}]}
    for name in (
        "budget-subscribers-actual-50.json",
        "budget-subscribers-actual-80.json",
        "budget-subscribers-forecasted-100.json",
    ):
        write(directory, name, subscriber)


def test_exact_hardened_foundation_passes(tmp_path: Path) -> None:
    populate(tmp_path)
    result = MODULE.verify(
        tmp_path,
        {"result": "PASS", "unexpected_resources": []},
        {"result": "PASS", "contention_blocked": True},
        {"result": "PASS", "owner_scoped_release": True},
    )

    assert result["result"] == "PASS"
    assert result["budget_notification_count"] == 3
    assert result["zero_workload_verified"] is True


def test_budget_notifications_without_optional_threshold_type_pass(tmp_path: Path) -> None:
    populate(tmp_path)
    write(
        tmp_path,
        "budget-notifications.json",
        {
            "Notifications": [
                {"NotificationType": "ACTUAL", "Threshold": 50},
                {"NotificationType": "ACTUAL", "Threshold": 80},
                {"NotificationType": "FORECASTED", "Threshold": 100},
            ]
        },
    )

    result = MODULE.verify(
        tmp_path,
        {"result": "PASS", "unexpected_resources": []},
        {"result": "PASS", "contention_blocked": True},
        {"result": "PASS", "owner_scoped_release": True},
    )

    assert result["result"] == "PASS"
    assert all(item["threshold_type"] == "PERCENTAGE" for item in result["budget_notifications"])


def test_absolute_value_budget_notification_remains_rejected(tmp_path: Path) -> None:
    populate(tmp_path)
    notifications_path = tmp_path / "budget-notifications.json"
    notifications = json.loads(notifications_path.read_text(encoding="utf-8"))
    notifications["Notifications"][0]["ThresholdType"] = "ABSOLUTE_VALUE"
    write(tmp_path, "budget-notifications.json", notifications)

    result = MODULE.verify(
        tmp_path,
        {"result": "PASS", "unexpected_resources": []},
        {"result": "PASS", "contention_blocked": True},
        {"result": "PASS", "owner_scoped_release": True},
    )

    assert result["result"] == "FAIL"
    assert "Budget notification thresholds are incomplete or unexpected" in result["errors"]


def test_failed_foundation_verification_reports_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    populate(tmp_path)
    write(tmp_path, "budget-notifications.json", {"Notifications": []})
    write(tmp_path, "preflight.json", {"result": "PASS", "unexpected_resources": []})
    write(tmp_path, "contention.json", {"result": "PASS", "contention_blocked": True})
    write(tmp_path, "release.json", {"result": "PASS", "owner_scoped_release": True})

    status = MODULE.main(
        [
            "verify_foundation.py",
            str(tmp_path),
            str(tmp_path / "preflight.json"),
            str(tmp_path / "contention.json"),
            str(tmp_path / "release.json"),
            str(tmp_path / "foundation-verification.json"),
        ]
    )

    assert status == 1
    assert "Budget notification thresholds are incomplete or unexpected" in capsys.readouterr().err


def test_public_bucket_or_workload_resource_fails(tmp_path: Path) -> None:
    populate(tmp_path)
    write(
        tmp_path,
        "bucket-public-access.json",
        {"PublicAccessBlockConfiguration": {"BlockPublicAcls": False}},
    )
    result = MODULE.verify(
        tmp_path,
        {"result": "FAIL", "unexpected_resources": ["arn:aws:s3:::atlasretail-live"]},
        {"result": "PASS", "contention_blocked": True},
        {"result": "PASS", "owner_scoped_release": True},
    )

    assert result["result"] == "FAIL"
    assert any("public-access" in error for error in result["errors"])
    assert any("zero-workload" in error for error in result["errors"])
