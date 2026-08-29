"""Guard the non-deploying AWS preflight contract."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "aws-read-only-preflight.yml"
SESSION_POLICY_BUILDER = ROOT / "scripts" / "build_read_only_session_policy.py"
TARGET = ROOT / ".github" / "atlas-target.json"


def session_policy() -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(SESSION_POLICY_BUILDER)],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    value = json.loads(completed.stdout)
    assert isinstance(value, dict)
    return value


def test_preflight_has_no_infrastructure_mutation_commands() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    forbidden = (
        "terraform apply",
        "terraform destroy",
        "cloudformation deploy",
        "aws s3 cp",
        "aws s3api put-",
        "aws s3api delete-",
        "aws dynamodb put-item",
        "aws dynamodb update-item",
        "aws dynamodb delete-item",
        "aws glue create-",
        "aws glue delete-",
        "aws glue start-job-run",
        "aws lambda invoke",
        "aws stepfunctions start-execution",
        "aws athena start-query-execution",
    )
    assert all(command not in workflow for command in forbidden)
    assert "aws sts get-caller-identity" in workflow
    assert "python scripts/capture_account_plan.py" in workflow
    assert "python scripts/verify_account_plan.py" in workflow
    assert "freetier upgrade-account-plan" not in workflow
    assert "python scripts/verify_preflight.py" in workflow
    assert '"${ACCOUNT_LEASE_TABLE}"' in workflow
    assert "infra/iam/atlasretail-github-role-policy.json" in workflow


def test_preflight_evidence_is_bound_to_the_workflow_source() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert '--source-identity "${EVIDENCE_DIR}/source-identity.json"' in workflow
    assert '--source-commit "${GITHUB_SHA}"' in workflow
    assert '--github-run-id "${GITHUB_RUN_ID}"' in workflow
    assert "path: evidence/preflight/${{ github.run_id }}" in workflow


def test_preflight_uses_a_restrictive_read_only_session() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    policy_loader = workflow.index("Load the restrictive read-only session policy")
    credential_setup = workflow.index("aws-actions/configure-aws-credentials@")

    assert policy_loader < credential_setup
    assert "python scripts/build_read_only_session_policy.py" in workflow
    assert "inline-session-policy: ${{ steps.session-policy.outputs.json }}" in workflow
    assert "allowed-account-ids: ${{ steps.target.outputs.aws_account_id }}" in workflow
    assert "role-duration-seconds: 900" in workflow
    assert "unset-current-credentials: true" in workflow
    assert "mask-aws-account-id: true" in workflow
    assert "action-timeout-s: 120" in workflow


def test_preflight_session_policy_is_an_exact_read_allowlist() -> None:
    policy = session_policy()
    actions = {
        action
        for statement in policy["Statement"]
        for action in (
            statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
        )
    }
    expected = {
        "dynamodb:DescribeTable",
        "dynamodb:GetItem",
        "freetier:GetAccountPlanState",
        "kms:DescribeKey",
        "kms:ListAliases",
        "s3:GetBucketLocation",
        "s3:GetObject",
        "s3:ListBucket",
        "sts:GetCallerIdentity",
        "tag:GetResources",
    }

    assert policy["Version"] == "2012-10-17"
    assert all(statement["Effect"] == "Allow" for statement in policy["Statement"])
    assert actions == expected
    assert all("*" not in action for action in actions)
    assert len(json.dumps(policy, separators=(",", ":"))) <= 2048


def test_preflight_session_policy_matches_the_canonical_backend() -> None:
    policy = session_policy()
    target = json.loads(TARGET.read_text(encoding="utf-8"))
    resources = {
        resource
        for statement in policy["Statement"]
        for resource in (
            statement["Resource"]
            if isinstance(statement["Resource"], list)
            else [statement["Resource"]]
        )
        if resource != "*"
    }
    bucket_arn = f"arn:aws:s3:::{target['terraform_state_bucket']}"

    assert resources == {
        bucket_arn,
        f"{bucket_arn}/{target['terraform_state_key']}",
        (
            f"arn:aws:dynamodb:{target['aws_region']}:{target['aws_account_id']}:"
            f"table/{target['terraform_lock_table']}"
        ),
        (
            f"arn:aws:dynamodb:{target['aws_region']}:{target['aws_account_id']}:"
            f"table/{target['account_lease_table']}"
        ),
    }
