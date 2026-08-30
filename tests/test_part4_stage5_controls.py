"""Structural and adversarial checks for Part 4 Stage 5 controls."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_part4_stage5_controls", ROOT / "scripts/validate_part4_stage5_controls.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_stage5_repository_proof_is_local_and_exact() -> None:
    result = MODULE.validate(ROOT)

    assert result["result"] == "PASS"
    assert result["claim_level"] == "LOCAL_VERIFIED"
    assert result["aws_execution"] is False
    assert result["managed_address_count"] == 40
    assert result["read_only_data_address_count"] == 6


def test_recovery_rejects_any_workload_start_command(tmp_path: Path) -> None:
    source = (ROOT / ".github/workflows/aws-bounded-lab-recovery.yml").read_text(encoding="utf-8")
    path = tmp_path / "recovery.yml"
    path.write_text(source + "\n# aws glue start-job-run\n", encoding="utf-8")

    with pytest.raises(MODULE.ControlsError, match="workload/create behavior"):
        MODULE.validate_recovery_workflow(path)


def test_recovery_rejects_missing_pre_oidc_authority_validation(tmp_path: Path) -> None:
    source = (ROOT / ".github/workflows/aws-bounded-lab-recovery.yml").read_text(encoding="utf-8")
    path = tmp_path / "recovery.yml"
    path.write_text(
        source.replace(
            "Independently validate immutable recovery authority before AWS access",
            "Untrusted authority step",
        ),
        encoding="utf-8",
    )

    with pytest.raises(MODULE.ControlsError, match="workflow step is missing"):
        MODULE.validate_recovery_workflow(path)


def test_lease_validator_rejects_expiry_takeover(tmp_path: Path) -> None:
    source = (ROOT / "scripts/manage_part4_lease.py").read_text(encoding="utf-8")
    path = tmp_path / "lease.py"
    path.write_text(source + '\nDANGEROUS = "expires_at < :now"\n', encoding="utf-8")

    with pytest.raises(MODULE.ControlsError, match="expiry takeover"):
        MODULE.validate_lease_source(path)


def test_ci_reproduces_and_retains_stage5_receipt() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert workflow.count("validate_part4_stage5_controls.py") == 2
    assert "part4-stage5-teardown-authority-${{ github.run_id }}" in workflow
    assert "part4-stage5-teardown-authority-second.json" in workflow
