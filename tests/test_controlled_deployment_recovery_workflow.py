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
    assert "envelope=(--exact-envelope)" in workflow
    assert "envelope=(--allow-partial-destroy)" in workflow
    assert 'terraform -chdir="${TF_DIR}" apply -auto-approve' in workflow
    assert "python scripts/verify_teardown.py" in workflow
    assert '"${EVIDENCE_DIR}/upstream/terraform-outputs.json"' in workflow

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
    plan = workflow.index("Create and validate the saved recovery destroy-only plan")
    apply = workflow.index("Apply only the validated saved recovery destroy plan")
    verify = workflow.index("Prove failed run teardown across AWS and Terraform inventories")
    release = workflow.index("Release only the verified recovery account-wide lease")
    cleanup = workflow.index("Remove ephemeral recovery outputs")
    summary = workflow.index("Build recovery evidence summary")
    upload = workflow.index("Upload final controlled-deployment recovery evidence")

    assert authority < lease < plan < apply < verify < release < cleanup < summary < upload
    assert "attribute_not_exists(lock_id) OR #owner = :expected_owner" in workflow
    assert "steps.verify_teardown.outcome == 'success'" in workflow
    assert "steps.destroy_plan.outcome == 'success'" in workflow
    assert '"claim": "AWS_TEARDOWN_VERIFIED" if all(checks.values()) else "NONE"' in workflow


def test_failed_recovery_handoff_proves_exact_lease_owner_without_requiring_a_plan() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "prior-recovery/recovery-lease.json" in workflow
    assert "python scripts/validate_recovery_handoff.py" in workflow
    assert "prior-recovery-handoff-verification.json" in workflow
    assert '--failed-run-id "${FAILED_RUN_ID}"' in workflow
    assert '--previous-recovery-run-id "${PREVIOUS_RECOVERY_RUN_ID}"' in workflow
    assert 'value["checks"]["saved_destroy_plan"] is True' not in workflow
