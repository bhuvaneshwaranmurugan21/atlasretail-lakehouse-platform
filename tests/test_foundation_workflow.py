from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

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
    assert "--query '{Item: Item}'" in workflow
    assert '--output json > "${CONTROL_DIR}/lease-after-release.json"' in workflow
    assert "owner_scoped_release" in workflow


@pytest.mark.parametrize(
    ("payload", "expected_return_code"),
    [
        ({"Item": None}, 0),
        ({"Item": {"lock_id": {"S": "portfolio-lab"}}}, 1),
    ],
)
def test_foundation_release_verifier_handles_missing_and_existing_leases(
    tmp_path: Path, payload: dict[str, object], expected_return_code: int
) -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    marker = "\"${EVIDENCE_DIR}/lease-release.json\" <<'PY'\n"
    verifier = textwrap.dedent(workflow.split(marker, maxsplit=1)[1].split("\n          PY")[0])
    response = tmp_path / "lease-after-release.json"
    evidence = tmp_path / "lease-release.json"
    response.write_text(json.dumps(payload), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-", str(response), str(evidence)],
        input=verifier,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == expected_return_code
    if expected_return_code == 0:
        assert json.loads(evidence.read_text(encoding="utf-8")) == {
            "result": "PASS",
            "owner_scoped_release": True,
        }
    else:
        assert not evidence.exists()


def test_template_contains_permanent_hardened_controls_and_budget_alerts() -> None:
    template = TEMPLATE.read_text(encoding="utf-8")

    assert template.count("DeletionPolicy: Retain") == 3
    assert template.count("PointInTimeRecoveryEnabled: true") == 2
    assert "TimeToLiveSpecification:" in template
    assert template.count("SubscriptionType: EMAIL") == 3
    assert "IncludeCredit: false" in template
