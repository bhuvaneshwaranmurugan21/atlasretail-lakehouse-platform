"""Adversarial checks for the deterministic Stage 6 readiness gate."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_part4_stage6_controls", ROOT / "scripts/validate_part4_stage6_controls.py"
)
assert SPEC and SPEC.loader
CONTROLS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTROLS)


def test_repository_stage6_controls_pass_deterministically() -> None:
    first = CONTROLS.validate(ROOT)
    second = CONTROLS.validate(ROOT)
    assert first == second
    assert first["result"] == "PASS"
    assert first["claim_level"] == "LOCAL_VERIFIED"
    assert first["aws_execution"] is False
    assert first["contract_version"] == "1.1.0"
    assert all(first["checks"].values())


def test_execution_credential_lifetime_cannot_be_weakened(tmp_path: Path) -> None:
    source = ROOT / CONTROLS.BOUNDED
    changed = source.read_text(encoding="utf-8").replace(
        "timeout-minutes: 55", "timeout-minutes: 100", 1
    )
    path = tmp_path / "bounded.yml"
    path.write_text(changed, encoding="utf-8")
    with pytest.raises(CONTROLS.ControlsError, match="OIDC lifetime"):
        CONTROLS.validate_bounded(path)


def test_prerequisite_admission_cannot_move_after_source_admission(tmp_path: Path) -> None:
    source = ROOT / CONTROLS.BOUNDED
    changed = source.read_text(encoding="utf-8").replace(
        "Admit only current-source prerequisite evidence",
        "Delayed prerequisite evidence",
        1,
    )
    path = tmp_path / "bounded.yml"
    path.write_text(changed, encoding="utf-8")
    with pytest.raises(CONTROLS.ControlsError, match="workflow step is missing"):
        CONTROLS.validate_bounded(path)


def test_destroy_binary_recheck_cannot_be_removed(tmp_path: Path) -> None:
    source = ROOT / CONTROLS.BOUNDED
    changed = source.read_text(encoding="utf-8").replace(
        "saved destroy plan binding changed", "destroy binding omitted", 1
    )
    path = tmp_path / "bounded.yml"
    path.write_text(changed, encoding="utf-8")
    with pytest.raises(CONTROLS.ControlsError, match="missing Stage 6 controls"):
        CONTROLS.validate_bounded(path)


def test_lease_recovery_cannot_apply_or_start_workload(tmp_path: Path) -> None:
    source = ROOT / CONTROLS.LEASE_RECOVERY
    changed = source.read_text(encoding="utf-8").replace(
        "set -euo pipefail", "set -euo pipefail\n          terraform apply", 1
    )
    path = tmp_path / "lease-recovery.yml"
    path.write_text(changed, encoding="utf-8")
    with pytest.raises(CONTROLS.ControlsError, match="mutation/workload"):
        CONTROLS.validate_lease_recovery(path)


def test_lease_recovery_requires_clean_proof_before_release(tmp_path: Path) -> None:
    source = ROOT / CONTROLS.LEASE_RECOVERY
    changed = source.read_text(encoding="utf-8").replace(
        "Prove no deployment and the exact live-or-absent pre-authority lease",
        "Unverified lease state",
        1,
    )
    path = tmp_path / "lease-recovery.yml"
    path.write_text(changed, encoding="utf-8")
    with pytest.raises(CONTROLS.ControlsError, match="workflow step is missing"):
        CONTROLS.validate_lease_recovery(path)
