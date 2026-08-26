from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "aws-plan-only.yml"


def test_workflow_is_read_only_beyond_temporary_backend_locking() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    forbidden = (
        "terraform apply",
        "terraform destroy",
        "cloudformation deploy",
        "aws s3 cp",
        "aws dynamodb put-item",
        "aws lambda invoke",
        "aws glue start-job-run",
        "aws stepfunctions start-execution",
    )
    assert all(command not in workflow for command in forbidden)
    assert 'terraform -chdir="${TF_DIR}" plan' in workflow
    assert "python scripts/validate_terraform_plan.py" in workflow
    assert "python scripts/verify_no_change.py" in workflow
    assert "python scripts/summarize_plan_evidence.py" in workflow


def test_workflow_checks_identity_budget_iam_and_managed_definition() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    required = (
        "aws sts get-caller-identity",
        "python scripts/capture_account_plan.py",
        "aws budgets describe-budget",
        "aws iam get-role-policy",
        "python scripts/verify_iam_parity.py",
        "aws stepfunctions validate-state-machine-definition",
    )
    assert all(command in workflow for command in required)
    assert "atlasretail.tfplan" not in workflow.split("Upload sanitized plan evidence")[1]
