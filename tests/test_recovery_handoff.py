from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_recovery_handoff.py"
SPEC = importlib.util.spec_from_file_location("validate_recovery_handoff", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

REPOSITORY = "owner/repository"
FAILED_RUN_ID = "100"
RECOVERY_RUN_ID = "200"


def evidence(saved_destroy_plan: bool = False) -> tuple[dict, dict, bytes]:
    lease = {
        "Item": {
            "lock_id": {"S": "portfolio-lab"},
            "owner": {"S": f"{REPOSITORY}/{RECOVERY_RUN_ID}"},
            "expires_at": {"N": "1788015281"},
        }
    }
    lease_bytes = (json.dumps(lease, indent=4) + "\n").encode()
    summary = {
        "project": "AtlasRetail",
        "proof": "failed-controlled-deployment-recovery",
        "recovery_run_id": RECOVERY_RUN_ID,
        "failed_run_id": FAILED_RUN_ID,
        "result": "FAIL",
        "claim": "NONE",
        "checks": {
            "immutable_authority": True,
            "saved_destroy_plan": saved_destroy_plan,
            "aws_and_terraform_clean": False,
            "budget_bound": True,
        },
        "artifact_hashes": {
            "recovery-lease.json": "sha256:" + hashlib.sha256(lease_bytes).hexdigest()
        },
    }
    return summary, lease, lease_bytes


def validate(summary: dict, lease: dict, lease_bytes: bytes) -> dict:
    return MODULE.validate(
        summary,
        lease,
        lease_bytes,
        repository=REPOSITORY,
        failed_run_id=FAILED_RUN_ID,
        previous_recovery_run_id=RECOVERY_RUN_ID,
    )


def test_early_failed_recovery_can_handoff_its_exact_lease() -> None:
    summary, lease, lease_bytes = evidence(saved_destroy_plan=False)

    proof = validate(summary, lease, lease_bytes)

    assert proof["result"] == "PASS"
    assert proof["claim"] == "FAILED_RECOVERY_HANDOFF_VERIFIED"
    assert proof["prior_saved_destroy_plan"] is False


def test_failed_recovery_with_a_saved_plan_can_also_handoff() -> None:
    summary, lease, lease_bytes = evidence(saved_destroy_plan=True)

    assert validate(summary, lease, lease_bytes)["result"] == "PASS"


def test_handoff_rejects_tampered_or_clean_claimed_evidence() -> None:
    summary, lease, lease_bytes = evidence()
    lease["Item"]["owner"]["S"] = f"{REPOSITORY}/wrong-run"
    rejected_owner = validate(summary, lease, lease_bytes)
    assert rejected_owner["result"] == "FAIL"
    assert "prior lease owner mismatch" in rejected_owner["errors"]

    summary, lease, lease_bytes = evidence()
    summary["checks"]["aws_and_terraform_clean"] = True
    rejected_claim = validate(summary, lease, lease_bytes)
    assert rejected_claim["result"] == "FAIL"
    assert "prior recovery must not claim a clean teardown" in rejected_claim["errors"]

    summary, lease, lease_bytes = evidence()
    rejected_hash = validate(summary, lease, lease_bytes + b"tampered")
    assert rejected_hash["result"] == "FAIL"
    assert "prior lease artifact hash mismatch" in rejected_hash["errors"]
