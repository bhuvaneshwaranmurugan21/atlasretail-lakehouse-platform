from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "aws-controlled-deployment-recovery.yml"


def test_recovery_is_manual_exact_source_and_destroy_only() -> None:
    parsed = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert set(parsed["on"]) == {"workflow_dispatch"}
    assert set(parsed["jobs"]) == {"recover"}
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "RECOVER_AND_DESTROY_FAILED_CANARY" in workflow
    assert "atlasretail-deployment-authority-${{ inputs.failed_run_id }}" in workflow
    assert "atlasretail-deployment-pre-teardown-${{ inputs.failed_run_id }}" in workflow
    assert "ref: ${{ steps.failed_source.outputs.source_commit }}" in workflow
    assert '--legacy-terraform-root "${TF_DIR}"' in workflow
    assert 'terraform -chdir="${TF_DIR}" plan -destroy' in workflow
    assert "--mode destroy --exact-envelope" in workflow
    assert 'terraform -chdir="${TF_DIR}" apply -auto-approve' in workflow
    assert "python scripts/verify_teardown.py" in workflow

    forbidden = (
        "terraform apply -auto-approve -var",
        "start-execution",
        "start-job-run",
        "lambda invoke",
        "start-query-execution",
    )
    assert all(value not in workflow for value in forbidden)


def test_recovery_lease_and_evidence_fail_closed() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    authority = workflow.index("Validate the failed run legacy authority")
    lease = workflow.index("Atomically recover only the failed run account-wide lease")
    plan = workflow.index("Create and validate the exact saved recovery destroy plan")
    apply = workflow.index("Apply only the validated saved recovery destroy plan")
    verify = workflow.index("Prove failed run teardown across AWS and Terraform inventories")
    release = workflow.index("Release only the verified recovery account-wide lease")
    cleanup = workflow.index("Remove ephemeral recovery outputs")
    summary = workflow.index("Build recovery evidence summary")
    upload = workflow.index("Upload final controlled-deployment recovery evidence")

    assert authority < lease < plan < apply < verify < release < cleanup < summary < upload
    assert "attribute_not_exists(lock_id) OR #owner = :failed_owner" in workflow
    assert "steps.verify_teardown.outcome == 'success'" in workflow
    assert '"claim": "AWS_TEARDOWN_VERIFIED" if all(checks.values()) else "NONE"' in workflow
