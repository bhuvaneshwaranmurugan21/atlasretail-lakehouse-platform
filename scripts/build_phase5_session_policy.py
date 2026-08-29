#!/usr/bin/env python3
"""Render fail-closed STS intersections for the Part 3 Phase 5 workflows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

MAX_SESSION_POLICY_CHARACTERS = 2048
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
    "athena:CreateWorkGroup",
    "athena:Get*",
    "athena:List*",
    "athena:TagResource",
    "athena:UntagResource",
    "athena:UpdateWorkGroup",
    "budgets:ViewBudget",
    "cloudwatch:Describe*",
    "cloudwatch:List*",
    "cloudwatch:PutMetricAlarm",
    "cloudwatch:TagResource",
    "cloudwatch:UntagResource",
    "dynamodb:CreateTable",
    "dynamodb:DeleteItem",
    "dynamodb:Describe*",
    "dynamodb:GetItem",
    "dynamodb:ListTagsOfResource",
    "dynamodb:PutItem",
    "dynamodb:Scan",
    "dynamodb:TagResource",
    "dynamodb:UntagResource",
    "dynamodb:Update*",
    "freetier:GetAccountPlanState",
    "glue:CreateDatabase",
    "glue:CreateJob",
    "glue:Get*",
    "glue:TagResource",
    "glue:UntagResource",
    "glue:Update*",
    "iam:CreateRole",
    "iam:Get*",
    "iam:List*",
    "iam:PassRole",
    "iam:PutRolePolicy",
    "iam:TagRole",
    "iam:UntagRole",
    "iam:UpdateAssumeRolePolicy",
    "kms:CreateAlias",
    "kms:CreateKey",
    "kms:DescribeKey",
    "kms:Get*",
    "kms:List*",
    "kms:PutKeyPolicy",
    "kms:TagResource",
    "kms:UntagResource",
    "kms:Update*",
    "lambda:AddPermission",
    "lambda:CreateFunction",
    "lambda:Get*",
    "lambda:List*",
    "lambda:RemovePermission",
    "lambda:TagResource",
    "lambda:UntagResource",
    "lambda:Update*",
    "logs:AssociateKmsKey",
    "logs:CreateLogGroup",
    "logs:DescribeLogGroups",
    "logs:FilterLogEvents",
    "logs:ListTagsForResource",
    "logs:PutRetentionPolicy",
    "logs:TagResource",
    "logs:UntagResource",
    "s3:CreateBucket",
    "s3:Get*",
    "s3:List*",
    "s3:Put*",
    "states:CreateStateMachine",
    "states:Describe*",
    "states:List*",
    "states:TagResource",
    "states:UntagResource",
    "states:Update*",
    "states:ValidateStateMachineDefinition",
    "sts:GetCallerIdentity",
    "tag:GetResources",
)

TEARDOWN_ACTIONS = (
    "athena:DeleteWorkGroup",
    "athena:Get*",
    "athena:List*",
    "budgets:ViewBudget",
    "cloudwatch:DeleteAlarms",
    "cloudwatch:Describe*",
    "cloudwatch:List*",
    "dynamodb:DeleteItem",
    "dynamodb:DeleteTable",
    "dynamodb:Describe*",
    "dynamodb:GetItem",
    "dynamodb:ListTagsOfResource",
    "dynamodb:PutItem",
    "dynamodb:Scan",
    "dynamodb:UpdateItem",
    "glue:DeleteDatabase",
    "glue:DeleteJob",
    "glue:Get*",
    "iam:DeleteRole",
    "iam:DeleteRolePolicy",
    "iam:Get*",
    "iam:List*",
    "kms:DeleteAlias",
    "kms:DescribeKey",
    "kms:DisableKey",
    "kms:Get*",
    "kms:List*",
    "kms:ScheduleKeyDeletion",
    "lambda:DeleteFunction",
    "lambda:Get*",
    "lambda:List*",
    "logs:DeleteLogGroup",
    "logs:DescribeLogGroups",
    "logs:FilterLogEvents",
    "logs:ListTagsForResource",
    "s3:DeleteBucket",
    "s3:DeleteBucketPolicy",
    "s3:DeleteObject",
    "s3:DeleteObjectVersion",
    "s3:Get*",
    "s3:List*",
    "s3:PutObject",
    "states:DeleteStateMachine",
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
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "Phase5PermissionIntersection",
                "Effect": "Allow",
                "Action": list(allowed),
                "Resource": "*",
            },
            {
                "Sid": "DenyWorkloadExecution",
                "Effect": "Deny",
                "Action": list(WORKLOAD_ACTIONS),
                "Resource": "*",
            },
        ],
    }


def render_policy(mode: str) -> str:
    rendered = json.dumps(build_policy(mode), separators=(",", ":"), sort_keys=True)
    if len(rendered) > MAX_SESSION_POLICY_CHARACTERS:
        raise ValueError("rendered session policy exceeds the STS 2048-character limit")
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
