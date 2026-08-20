from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "aws-controlled-deployment.yml"


def test_controlled_deployment_is_manual_and_bounded() -> None:
    parsed = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert set(parsed["on"]) == {"workflow_dispatch"}
    assert set(parsed["jobs"]) == {"deploy", "teardown"}
    assert parsed["jobs"]["teardown"]["needs"] == "deploy"
    assert parsed["jobs"]["teardown"]["if"] == "${{ always() }}"

    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'test "${GITHUB_REF}" = "refs/heads/main"' in workflow
    assert 'test "${GITHUB_ACTOR}" = "bhuvaneshwaranmurugan21"' in workflow
    assert 'test "${BUDGET_CEILING_USD}" -le 5' in workflow
    assert "DEPLOY_ATLASRETAIL_CANARY" in workflow
    assert "DESTROY_AFTER_VERIFICATION" in workflow


def test_controlled_deployment_has_exact_apply_and_independent_teardown() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    required = (
        "python scripts/verify_iam_parity.py",
        "python scripts/verify_preflight.py",
        "python scripts/validate_terraform_plan.py",
        "python scripts/verify_deployment.py",
        "python scripts/verify_teardown.py",
        "python scripts/summarize_deployment_evidence.py",
        "terraform-apply-plan-hashes.txt",
        "terraform-destroy-plan-hashes.txt",
    )
    assert all(value in workflow for value in required)
    assert 'terraform -chdir="${TF_DIR}" apply -auto-approve' in workflow
    assert '"${GITHUB_WORKSPACE}/${CONTROL_DIR}/apply.tfplan"' in workflow
    assert '"${GITHUB_WORKSPACE}/${CONTROL_DIR}/destroy.tfplan"' in workflow


def test_controlled_deployment_cannot_execute_a_data_workload() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    forbidden = (
        "atlasretail.cli generate",
        "start-execution",
        "start-job-run",
        "lambda invoke",
        "start-query-execution",
        "upload_immutable_batch.py",
    )
    assert all(value not in workflow for value in forbidden)
    artifact_section = workflow.split("Upload final controlled-deployment evidence", maxsplit=1)[1]
    assert ".control" not in artifact_section
