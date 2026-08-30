#!/usr/bin/env python3
"""Build compact, region-bound STS intersections for the Part 4 lab."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REGION = "ap-southeast-2"
MAX_PLAINTEXT = 2048
MAX_PACKED_RISK = 925
REGIONAL = (
    "athena:*",
    "cloudwatch:*",
    "dynamodb:*",
    "glue:*",
    "kms:*",
    "lambda:*",
    "logs:*",
    "s3:*",
    "states:*",
)
GLOBAL = (
    "budgets:ViewBudget",
    "freetier:GetAccountPlanState",
    "iam:*",
    "sts:GetCallerIdentity",
    "tag:GetResources",
)
WORKLOAD = (
    "athena:StartQueryExecution",
    "glue:StartJobRun",
    "lambda:InvokeFunction",
    "states:StartExecution",
)
EXECUTION_DESTRUCTIVE = (
    "athena:Delete*",
    "cloudwatch:Delete*",
    "dynamodb:DeleteTable",
    "glue:Delete*",
    "iam:Delete*",
    "kms:ScheduleKeyDeletion",
    "lambda:Delete*",
    "logs:Delete*",
    "s3:DeleteBucket",
    "states:Delete*",
)
TEARDOWN_CREATE_OR_UPDATE = (
    "athena:Create*",
    "cloudwatch:PutMetricAlarm",
    "dynamodb:CreateTable",
    "glue:Create*",
    "glue:Update*",
    "iam:Create*",
    "iam:Put*",
    "kms:Create*",
    "lambda:Create*",
    "lambda:Update*",
    "logs:CreateLogGroup",
    "s3:CreateBucket",
    "states:Create*",
    "states:Update*",
)


def build_policy(mode: str) -> dict[str, Any]:
    if mode not in {"execution", "teardown"}:
        raise ValueError("mode must be execution or teardown")
    statements: list[dict[str, Any]] = [
        {
            "Effect": "Allow",
            "Action": list(REGIONAL),
            "Resource": "*",
            "Condition": {"StringEquals": {"aws:RequestedRegion": REGION}},
        },
        {"Effect": "Allow", "Action": list(GLOBAL), "Resource": "*"},
    ]
    denied = EXECUTION_DESTRUCTIVE if mode == "execution" else WORKLOAD + TEARDOWN_CREATE_OR_UPDATE
    statements.append({"Effect": "Deny", "Action": list(denied), "Resource": "*"})
    return {"Version": "2012-10-17", "Statement": statements}


def render_policy(mode: str) -> str:
    rendered = json.dumps(build_policy(mode), separators=(",", ":"), sort_keys=True)
    if len(rendered) > MAX_PLAINTEXT:
        raise ValueError("session policy exceeds the STS plaintext limit")
    if len(rendered) > MAX_PACKED_RISK:
        raise ValueError("session policy exceeds the empirically safe packed-size budget")
    return rendered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("execution", "teardown"), required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--github-output", type=Path)
    arguments = parser.parse_args()
    rendered = render_policy(arguments.mode)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(rendered + "\n", encoding="utf-8")
    if arguments.github_output:
        with arguments.github_output.open("a", encoding="utf-8") as handle:
            handle.write(f"policy={rendered}\n")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
