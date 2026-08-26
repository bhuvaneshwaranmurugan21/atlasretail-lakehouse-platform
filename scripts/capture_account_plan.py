"""Capture AWS account-plan state with a narrow member-account fallback."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def normalize_result(
    returncode: int,
    stdout: str,
    stderr: str,
    account_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Normalize a successful lookup or the exact member-account missing-data response."""
    if returncode == 0:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return None, "GetAccountPlanState returned invalid JSON"
        if not isinstance(payload, dict):
            return None, "GetAccountPlanState returned a non-object response"
        payload["accountPlanLookupResult"] = "FOUND"
        return payload, None

    missing_marker = f"Missing data for account: {account_id}"
    if returncode == 254 and "ResourceNotFoundException" in stderr and missing_marker in stderr:
        return {
            "accountId": account_id,
            "accountPlanLookupResult": "NOT_FOUND",
            "errorCode": "ResourceNotFoundException",
        }, None

    detail = stderr.strip() or f"GetAccountPlanState failed with exit code {returncode}"
    return None, detail


def main(arguments: list[str]) -> int:
    if len(arguments) != 3:
        print("usage: capture_account_plan.py OUTPUT_JSON AWS_ACCOUNT_ID", file=sys.stderr)
        return 2

    output = Path(arguments[1])
    account_id = arguments[2]
    if len(account_id) != 12 or not account_id.isdigit():
        print("AWS account ID must contain exactly 12 digits", file=sys.stderr)
        return 2

    completed = subprocess.run(
        [
            "aws",
            "freetier",
            "get-account-plan-state",
            "--region",
            "us-east-1",
            "--output",
            "json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    payload, error = normalize_result(
        completed.returncode,
        completed.stdout,
        completed.stderr,
        account_id,
    )
    if payload is None:
        print(error, file=sys.stderr)
        return 1

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
