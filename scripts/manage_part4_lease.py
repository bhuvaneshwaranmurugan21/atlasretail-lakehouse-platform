#!/usr/bin/env python3
"""Manage the attempt-bound Part 4 account lease without silent expiry takeover."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

LOCK_ID = "portfolio-lab"
LEASE_SECONDS = 7 * 24 * 60 * 60


class LeaseError(RuntimeError):
    """Raised when a conditional lease transition cannot be proved."""


def aws(arguments: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        ["aws", *arguments, "--output", "json", "--no-cli-pager"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise LeaseError(detail or f"AWS CLI exited {completed.returncode}")
    try:
        value = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as error:
        raise LeaseError("AWS CLI returned unreadable JSON") from error
    if not isinstance(value, dict):
        raise LeaseError("AWS CLI did not return a JSON object")
    return value


def string(item: dict[str, Any], name: str) -> str | None:
    value = item.get(name)
    return value.get("S") if isinstance(value, dict) else None


def consistent_item(table: str, region: str) -> dict[str, Any]:
    response = aws(
        [
            "dynamodb",
            "get-item",
            "--region",
            region,
            "--table-name",
            table,
            "--key",
            json.dumps({"lock_id": {"S": LOCK_ID}}, separators=(",", ":")),
            "--consistent-read",
        ]
    )
    item = response.get("Item")
    if not isinstance(item, dict):
        raise LeaseError("account lease is absent")
    return item


def expected_common(args: argparse.Namespace) -> dict[str, str]:
    return {
        "lock_id": LOCK_ID,
        "owner": args.owner,
        "run_attempt": args.run_attempt,
        "source_commit": args.source_commit,
        "contract_sha256": args.contract_sha256,
        "target_sha256": args.target_sha256,
    }


def verify_fields(item: dict[str, Any], expected: dict[str, str], state: str) -> None:
    for name, value in expected.items():
        if string(item, name) != value:
            raise LeaseError(f"account lease has wrong {name}")
    if string(item, "state") != state:
        raise LeaseError(f"account lease state is not {state}")


def acquire(args: argparse.Namespace) -> dict[str, Any]:
    now = int(time.time())
    values = {
        **{name: {"S": value} for name, value in expected_common(args).items()},
        "state": {"S": "ACQUIRED"},
        "acquired_at": {"N": str(now)},
        "expires_at": {"N": str(now + LEASE_SECONDS)},
    }
    aws(
        [
            "dynamodb",
            "put-item",
            "--region",
            args.region,
            "--table-name",
            args.table,
            "--item",
            json.dumps(values, separators=(",", ":")),
            "--condition-expression",
            "attribute_not_exists(lock_id)",
        ]
    )
    item = consistent_item(args.table, args.region)
    verify_fields(item, expected_common(args), "ACQUIRED")
    return {
        "schema_version": "1.0",
        "proof": "part4-lease-acquisition",
        "result": "PASS",
        "lock_id": LOCK_ID,
        "owner": args.owner,
        "run_attempt": args.run_attempt,
        "source_commit": args.source_commit,
        "state": "ACQUIRED",
        "silent_expiry_takeover": False,
        "consistent_read": True,
        "expires_at": int(item["expires_at"]["N"]),
    }


def bind(args: argparse.Namespace) -> dict[str, Any]:
    names = {"#owner": "owner", "#state": "state"}
    values = {
        ":owner": {"S": args.owner},
        ":attempt": {"S": args.run_attempt},
        ":source": {"S": args.source_commit},
        ":acquired": {"S": "ACQUIRED"},
        ":bound": {"S": "AUTHORITY_BOUND"},
        ":authority": {"S": args.authority_sha256},
        ":artifact_id": {"S": args.artifact_id},
        ":artifact_digest": {"S": args.artifact_digest},
    }
    aws(
        [
            "dynamodb",
            "update-item",
            "--region",
            args.region,
            "--table-name",
            args.table,
            "--key",
            json.dumps({"lock_id": {"S": LOCK_ID}}, separators=(",", ":")),
            "--condition-expression",
            "#owner = :owner AND run_attempt = :attempt AND source_commit = :source "
            "AND #state = :acquired AND attribute_not_exists(authority_sha256)",
            "--update-expression",
            "SET #state = :bound, authority_sha256 = :authority, "
            "authority_artifact_id = :artifact_id, authority_artifact_digest = :artifact_digest",
            "--expression-attribute-names",
            json.dumps(names, separators=(",", ":")),
            "--expression-attribute-values",
            json.dumps(values, separators=(",", ":")),
        ]
    )
    item = consistent_item(args.table, args.region)
    verify_fields(item, expected_common(args), "AUTHORITY_BOUND")
    for name, expected in (
        ("authority_sha256", args.authority_sha256),
        ("authority_artifact_id", args.artifact_id),
        ("authority_artifact_digest", args.artifact_digest),
    ):
        if string(item, name) != expected:
            raise LeaseError(f"account lease has wrong {name}")
    return {
        "schema_version": "1.0",
        "proof": "part4-lease-authority-binding",
        "result": "PASS",
        "lock_id": LOCK_ID,
        "owner": args.owner,
        "run_attempt": args.run_attempt,
        "source_commit": args.source_commit,
        "state": "AUTHORITY_BOUND",
        "authority_sha256": args.authority_sha256,
        "authority_artifact_id": args.artifact_id,
        "authority_artifact_digest": args.artifact_digest,
        "consistent_read": True,
    }


def verify(args: argparse.Namespace) -> dict[str, Any]:
    item = consistent_item(args.table, args.region)
    verify_fields(item, expected_common(args), args.expected_state)
    if string(item, "authority_sha256") != args.authority_sha256:
        raise LeaseError("account lease authority digest differs")
    return {
        "schema_version": "1.0",
        "proof": "part4-lease-authority-verification",
        "result": "PASS",
        "lock_id": LOCK_ID,
        "owner": args.owner,
        "run_attempt": args.run_attempt,
        "source_commit": args.source_commit,
        "state": args.expected_state,
        "authority_sha256": args.authority_sha256,
        "consistent_read": True,
    }


def verify_acquired(args: argparse.Namespace) -> dict[str, Any]:
    """Prove an exact pre-authority lease without permitting state takeover."""
    item = consistent_item(args.table, args.region)
    verify_fields(item, expected_common(args), "ACQUIRED")
    if string(item, "authority_sha256") is not None:
        raise LeaseError("pre-authority lease unexpectedly contains teardown authority")
    return {
        "schema_version": "1.0",
        "proof": "part4-lease-pre-authority-verification",
        "result": "PASS",
        "lock_id": LOCK_ID,
        "owner": args.owner,
        "run_attempt": args.run_attempt,
        "source_commit": args.source_commit,
        "contract_sha256": args.contract_sha256,
        "target_sha256": args.target_sha256,
        "state": "ACQUIRED",
        "authority_absent": True,
        "consistent_read": True,
    }


def recover(args: argparse.Namespace) -> dict[str, Any]:
    recovery_owner = args.recovery_owner
    names = {"#owner": "owner", "#state": "state"}
    values = {
        ":failed_owner": {"S": args.owner},
        ":attempt": {"S": args.run_attempt},
        ":source": {"S": args.source_commit},
        ":authority": {"S": args.authority_sha256},
        ":bound": {"S": "AUTHORITY_BOUND"},
        ":recovery": {"S": "RECOVERY_BOUND"},
        ":recovery_owner": {"S": recovery_owner},
    }
    mode = "EXACT_OWNER_TRANSITION"
    try:
        aws(
            [
                "dynamodb",
                "update-item",
                "--region",
                args.region,
                "--table-name",
                args.table,
                "--key",
                json.dumps({"lock_id": {"S": LOCK_ID}}, separators=(",", ":")),
                "--condition-expression",
                "#owner = :failed_owner AND run_attempt = :attempt "
                "AND source_commit = :source AND authority_sha256 = :authority "
                "AND #state = :bound",
                "--update-expression",
                "SET #owner = :recovery_owner, #state = :recovery",
                "--expression-attribute-names",
                json.dumps(names, separators=(",", ":")),
                "--expression-attribute-values",
                json.dumps(values, separators=(",", ":")),
            ]
        )
    except LeaseError as error:
        if "ConditionalCheckFailedException" not in str(error):
            raise
        mode = "ABSENT_LEASE_RECOVERY_ACQUISITION"
        now = int(time.time())
        item = {
            "lock_id": {"S": LOCK_ID},
            "owner": {"S": recovery_owner},
            "failed_owner": {"S": args.owner},
            "run_attempt": {"S": args.run_attempt},
            "source_commit": {"S": args.source_commit},
            "contract_sha256": {"S": args.contract_sha256},
            "target_sha256": {"S": args.target_sha256},
            "authority_sha256": {"S": args.authority_sha256},
            "state": {"S": "RECOVERY_BOUND"},
            "acquired_at": {"N": str(now)},
            "expires_at": {"N": str(now + LEASE_SECONDS)},
        }
        aws(
            [
                "dynamodb",
                "put-item",
                "--region",
                args.region,
                "--table-name",
                args.table,
                "--item",
                json.dumps(item, separators=(",", ":")),
                "--condition-expression",
                "attribute_not_exists(lock_id)",
            ]
        )
    item = consistent_item(args.table, args.region)
    expected = expected_common(args)
    expected["owner"] = recovery_owner
    verify_fields(item, expected, "RECOVERY_BOUND")
    if string(item, "authority_sha256") != args.authority_sha256:
        raise LeaseError("recovery lease authority digest differs")
    return {
        "schema_version": "1.0",
        "proof": "part4-lease-recovery-binding",
        "result": "PASS",
        "mode": mode,
        "lock_id": LOCK_ID,
        "failed_owner": args.owner,
        "owner": recovery_owner,
        "run_attempt": args.run_attempt,
        "source_commit": args.source_commit,
        "state": "RECOVERY_BOUND",
        "authority_sha256": args.authority_sha256,
        "consistent_read": True,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "operation", choices=("acquire", "bind", "verify", "verify-acquired", "recover")
    )
    result.add_argument("--table", required=True)
    result.add_argument("--region", required=True)
    result.add_argument("--owner", required=True)
    result.add_argument("--run-attempt", required=True)
    result.add_argument("--source-commit", required=True)
    result.add_argument("--contract-sha256", required=True)
    result.add_argument("--target-sha256", required=True)
    result.add_argument("--authority-sha256")
    result.add_argument("--artifact-id")
    result.add_argument("--artifact-digest")
    result.add_argument("--expected-state", choices=("AUTHORITY_BOUND", "RECOVERY_BOUND"))
    result.add_argument("--recovery-owner")
    result.add_argument("--output", type=Path, required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.operation in {"bind", "verify", "recover"} and not args.authority_sha256:
            raise LeaseError("authority SHA-256 is required")
        if args.operation == "bind" and not (args.artifact_id and args.artifact_digest):
            raise LeaseError("authority artifact identity is required")
        if args.operation == "verify" and not args.expected_state:
            raise LeaseError("expected lease state is required")
        if args.operation == "recover" and not args.recovery_owner:
            raise LeaseError("recovery owner is required")
        operation = {
            "acquire": acquire,
            "bind": bind,
            "verify": verify,
            "verify-acquired": verify_acquired,
            "recover": recover,
        }[args.operation]
        evidence = operation(args)
    except LeaseError as error:
        evidence = {
            "schema_version": "1.0",
            "proof": f"part4-lease-{args.operation}",
            "result": "FAIL",
            "errors": [str(error)],
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if evidence["result"] != "PASS":
        print(json.dumps(evidence, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
