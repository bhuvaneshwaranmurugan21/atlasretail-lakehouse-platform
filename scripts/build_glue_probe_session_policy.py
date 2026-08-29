#!/usr/bin/env python3
"""Render the run-scoped STS session policy for the definition-only Glue probe."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

TARGET = json.loads(
    (Path(__file__).resolve().parents[1] / ".github" / "atlas-target.json").read_text(
        encoding="utf-8"
    )
)
MAX_SESSION_POLICY_CHARACTERS = 2048
WORKLOAD_ACTIONS = (
    "athena:StartQueryExecution",
    "glue:StartJobRun",
    "lambda:InvokeFunction",
    "states:StartExecution",
)


def validate_run_id(run_id: str) -> None:
    if re.fullmatch(r"[1-9][0-9]{0,19}", run_id) is None:
        raise ValueError("run ID must be a positive integer containing at most 20 digits")


def build_policy(run_id: str, mode: str) -> dict[str, Any]:
    """Return the exact probe or cleanup permission intersection."""
    validate_run_id(run_id)
    if mode not in {"probe", "cleanup"}:
        raise ValueError("mode must be probe or cleanup")

    account = TARGET["aws_account_id"]
    region = TARGET["aws_region"]
    role_name = f"atlasretail-probe-{run_id}-glue"
    job_name = f"atlasretail-probe-{run_id}"
    role_arn = f"arn:aws:iam::{account}:role/{role_name}"
    job_arn = f"arn:aws:glue:{region}:{account}:job/{job_name}"

    iam_actions = [
        "iam:DeleteRole",
        "iam:GetRole",
        "iam:ListAttachedRolePolicies",
        "iam:ListRolePolicies",
        "iam:ListRoleTags",
    ]
    glue_actions = [
        "glue:DeleteJob",
        "glue:GetJob",
        "glue:GetJobRuns",
        "glue:GetTags",
    ]
    statements: list[dict[str, Any]] = [
        {
            "Sid": "CallerIdentity",
            "Effect": "Allow",
            "Action": "sts:GetCallerIdentity",
            "Resource": "*",
        }
    ]
    if mode == "probe":
        iam_actions.extend(("iam:CreateRole", "iam:TagRole"))
        glue_actions.extend(("glue:CreateJob", "glue:TagResource"))
        statements.append(
            {
                "Sid": "PassOnlyProbeRoleToGlue",
                "Effect": "Allow",
                "Action": "iam:PassRole",
                "Resource": role_arn,
                "Condition": {"StringEquals": {"iam:PassedToService": "glue.amazonaws.com"}},
            }
        )
    statements.extend(
        (
            {
                "Sid": "ExactProbeRole",
                "Effect": "Allow",
                "Action": sorted(iam_actions),
                "Resource": role_arn,
            },
            {
                "Sid": "ExactProbeJob",
                "Effect": "Allow",
                "Action": sorted(glue_actions),
                "Resource": job_arn,
            },
            {
                "Sid": "DenyWorkloadExecution",
                "Effect": "Deny",
                "Action": list(WORKLOAD_ACTIONS),
                "Resource": "*",
            },
        )
    )
    return {"Version": "2012-10-17", "Statement": statements}


def render_policy(run_id: str, mode: str) -> str:
    rendered = json.dumps(build_policy(run_id, mode), separators=(",", ":"), sort_keys=True)
    if len(rendered) > MAX_SESSION_POLICY_CHARACTERS:
        raise ValueError("rendered session policy exceeds the STS 2048-character limit")
    return rendered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--mode", choices=("probe", "cleanup"), required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    rendered = render_policy(args.run_id, args.mode)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
