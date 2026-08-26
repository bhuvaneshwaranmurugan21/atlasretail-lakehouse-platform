"""Guard the non-deploying AWS preflight contract."""

from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "aws-read-only-preflight.yml"


def test_preflight_has_no_infrastructure_mutation_commands() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    forbidden = (
        "terraform apply",
        "terraform destroy",
        "cloudformation deploy",
        "aws s3 cp",
        "aws dynamodb put-item",
    )
    assert all(command not in workflow for command in forbidden)
    assert "aws sts get-caller-identity" in workflow
    assert "python scripts/capture_account_plan.py" in workflow
    assert "python scripts/verify_account_plan.py" in workflow
    assert "freetier upgrade-account-plan" not in workflow
    assert "python scripts/verify_preflight.py" in workflow
    assert "infra/iam/atlasretail-github-role-policy.json" in workflow
