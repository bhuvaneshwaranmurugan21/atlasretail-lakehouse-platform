from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "foundation.yml"
TEMPLATE = ROOT / "infra" / "foundation" / "template.yml"


def test_foundation_requires_confirmation_secret_and_live_iam_parity() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert 'test "${CONFIRM_DEPLOY}" = "DEPLOY_ATLASRETAIL_FOUNDATION"' in workflow
    assert "secrets.AWS_BUDGET_ALERT_EMAIL" in workflow
    assert "python scripts/verify_iam_parity.py" in workflow
    assert "python scripts/verify_foundation.py" in workflow
    assert "python scripts/verify_preflight.py" in workflow


def test_foundation_proves_conditional_lease_contention_and_release() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "bash scripts/acquire_lock.sh" in workflow
    assert "ConditionalCheckFailedException" in workflow
    assert "bash scripts/release_lock.sh" in workflow
    assert "owner_scoped_release" in workflow


def test_template_contains_permanent_hardened_controls_and_budget_alerts() -> None:
    template = TEMPLATE.read_text(encoding="utf-8")

    assert template.count("DeletionPolicy: Retain") == 3
    assert template.count("PointInTimeRecoveryEnabled: true") == 2
    assert "TimeToLiveSpecification:" in template
    assert template.count("SubscriptionType: EMAIL") == 3
    assert "IncludeCredit: false" in template
