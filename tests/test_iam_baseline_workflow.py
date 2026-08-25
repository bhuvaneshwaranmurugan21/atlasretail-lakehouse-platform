from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "aws-iam-baseline.yml"


def test_iam_baseline_is_manual_read_only_and_sanitized() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "VERIFY_ATLASRETAIL_IAM" in workflow
    assert "python scripts/verify_iam_parity.py" in workflow
    assert "evidence/iam/${{ github.run_id }}" in workflow
    for forbidden in ("put-role-policy", "update-assume-role-policy", "terraform apply"):
        assert forbidden not in workflow
