#!/usr/bin/env python3
"""Render fail-closed STS intersections for the Part 3 Phase 5 workflows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

MAX_SESSION_POLICY_CHARACTERS = 2048
# STS also applies a separate opaque packed-policy limit. The exact deploy and
# teardown lists were below the documented 2,048-character plaintext limit but
# AWS rejected them at 151% and 112% packed size. The plan policy in this size
# class has already been exercised successfully through this account's OIDC
# role, so fail locally before another workflow can submit a larger document.
MAX_PACKED_POLICY_PLAINTEXT_BUDGET = 900
WORKLOAD_ACTIONS = (
    "athena:StartQueryExecution",
    "glue:StartJobRun",
    "lambda:InvokeFunction",
    "states:StartExecution",
)
PLAN_ACTIONS = (
    "athena:Get*",
    "athena:List*",
    "budgets:ViewBudget",
    "cloudwatch:Describe*",
    "cloudwatch:Get*",
    "cloudwatch:List*",
    "dynamodb:DeleteItem",
    "dynamodb:Describe*",
    "dynamodb:GetItem",
    "dynamodb:PutItem",
    "dynamodb:Scan",
    "dynamodb:UpdateItem",
    "freetier:GetAccountPlanState",
    "glue:Get*",
    "iam:Get*",
    "iam:List*",
    "kms:DescribeKey",
    "kms:Get*",
    "kms:List*",
    "lambda:Get*",
    "lambda:List*",
    "logs:Describe*",
    "logs:FilterLogEvents",
    "logs:Get*",
    "logs:List*",
    "s3:Get*",
    "s3:List*",
    "states:Describe*",
    "states:List*",
    "states:ValidateStateMachineDefinition",
    "sts:GetCallerIdentity",
    "tag:GetResources",
)

DEPLOY_ACTIONS = (
    "athena:*",
    "budgets:ViewBudget",
    "cloudwatch:*",
    "dynamodb:*",
    "freetier:GetAccountPlanState",
    "glue:*",
    "iam:*",
    "kms:*",
    "lambda:*",
    "logs:*",
    "s3:*",
    "states:*",
    "sts:GetCallerIdentity",
    "tag:GetResources",
)

# The deploy allow patterns are compact enough for STS, while this deny set
# makes their intersection with the exact tracked/live role policy identical to
# the former explicit deploy allowlist. Destructive and workload operations
# therefore cannot become effective deploy permissions.
DEPLOY_OUT_OF_MODE_ACTIONS = (
    "athena:Delete*",
    "athena:Stop*",
    "cloudwatch:Delete*",
    "dynamodb:DeleteTable",
    "glue:Delete*",
    "iam:Delete*",
    "kms:CreateGrant",
    "kms:Decrypt",
    "kms:Delete*",
    "kms:Disable*",
    "kms:Enable*",
    "kms:Encrypt",
    "kms:GenerateDataKey",
    "kms:RevokeGrant",
    "kms:Schedule*",
    "lambda:Delete*",
    "logs:Delete*",
    "s3:Delete*",
    "states:Delete*",
    "states:GetExecutionHistory",
    "states:Stop*",
)

TEARDOWN_ACTIONS = (
    "athena:Delete*",
    "athena:Get*",
    "athena:List*",
    "budgets:ViewBudget",
    "cloudwatch:Delete*",
    "cloudwatch:Describe*",
    "cloudwatch:List*",
    "dynamodb:Delete*",
    "dynamodb:Describe*",
    "dynamodb:Get*",
    "dynamodb:List*",
    "dynamodb:PutItem",
    "dynamodb:Scan",
    "dynamodb:UpdateItem",
    "glue:Delete*",
    "glue:Get*",
    "iam:Delete*",
    "iam:Get*",
    "iam:List*",
    "kms:Delete*",
    "kms:Describe*",
    "kms:Disable*",
    "kms:Get*",
    "kms:List*",
    "kms:Schedule*",
    "lambda:Delete*",
    "lambda:Get*",
    "lambda:List*",
    "logs:Delete*",
    "logs:Describe*",
    "logs:Filter*",
    "logs:List*",
    "s3:Delete*",
    "s3:Get*",
    "s3:List*",
    "s3:PutObject",
    "states:Delete*",
    "states:Describe*",
    "states:List*",
    "sts:GetCallerIdentity",
    "tag:GetResources",
)


def build_policy(mode: str) -> dict[str, Any]:
    if mode not in {"plan", "deploy", "teardown"}:
        raise ValueError("mode must be plan, deploy, or teardown")
    allowed = {
        "plan": PLAN_ACTIONS,
        "deploy": DEPLOY_ACTIONS,
        "teardown": TEARDOWN_ACTIONS,
    }[mode]
    statements: list[dict[str, Any]] = [
        {
            "Effect": "Allow",
            "Action": list(allowed),
            "Resource": "*",
        },
        {
            "Effect": "Deny",
            "Action": list(WORKLOAD_ACTIONS),
            "Resource": "*",
        },
    ]
    if mode == "deploy":
        statements.append(
            {
                "Effect": "Deny",
                "Action": list(DEPLOY_OUT_OF_MODE_ACTIONS),
                "Resource": "*",
            }
        )
    return {
        "Version": "2012-10-17",
        "Statement": statements,
    }


def render_policy(mode: str) -> str:
    rendered = json.dumps(build_policy(mode), separators=(",", ":"), sort_keys=True)
    if len(rendered) > MAX_SESSION_POLICY_CHARACTERS:
        raise ValueError("rendered session policy exceeds the STS 2048-character limit")
    if len(rendered) > MAX_PACKED_POLICY_PLAINTEXT_BUDGET:
        raise ValueError("rendered session policy exceeds the packed-size risk budget")
    return rendered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("plan", "deploy", "teardown"), required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rendered = render_policy(args.mode)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
