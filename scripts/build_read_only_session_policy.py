#!/usr/bin/env python3
"""Build the exact resource-scoped session policy for the AWS preflight."""

from __future__ import annotations

import json
import sys
from typing import Any

from load_aws_target import load_target

MAX_SESSION_POLICY_CHARACTERS = 2048


def build_policy(target: dict[str, Any]) -> dict[str, Any]:
    account = target["aws_account_id"]
    region = target["aws_region"]
    bucket = target["terraform_state_bucket"]
    state_key = target["terraform_state_key"]
    lock_table = target["terraform_lock_table"]
    lease_table = target["account_lease_table"]
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ReadIdentityAccountPlanAndTaggedInventory",
                "Effect": "Allow",
                "Action": [
                    "freetier:GetAccountPlanState",
                    "sts:GetCallerIdentity",
                    "tag:GetResources",
                ],
                "Resource": "*",
            },
            {
                "Sid": "ReadTerraformStateBucket",
                "Effect": "Allow",
                "Action": ["s3:GetBucketLocation", "s3:ListBucket"],
                "Resource": f"arn:aws:s3:::{bucket}",
            },
            {
                "Sid": "ReadTerraformStateObject",
                "Effect": "Allow",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{bucket}/{state_key}",
            },
            {
                "Sid": "ReadTerraformLockMetadata",
                "Effect": "Allow",
                "Action": ["dynamodb:DescribeTable", "dynamodb:GetItem"],
                "Resource": [
                    f"arn:aws:dynamodb:{region}:{account}:table/{lock_table}",
                    f"arn:aws:dynamodb:{region}:{account}:table/{lease_table}",
                ],
            },
            {
                "Sid": "InspectPendingKmsCleanup",
                "Effect": "Allow",
                "Action": ["kms:DescribeKey", "kms:ListAliases"],
                "Resource": "*",
            },
        ],
    }


def main() -> int:
    encoded = json.dumps(build_policy(load_target()), separators=(",", ":"))
    if len(encoded) > MAX_SESSION_POLICY_CHARACTERS:
        print("read-only session policy exceeds the AWS STS character limit", file=sys.stderr)
        return 1
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
