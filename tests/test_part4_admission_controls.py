from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from atlasretail.part4_admission import AdmissionError

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "validate_part4_admission_controls.py"
SPEC = importlib.util.spec_from_file_location("part4_admission_controls", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_current_stage3_controls_pass() -> None:
    result = MODULE.validate(ROOT)
    assert result["result"] == "PASS"
    assert result["claim_level"] == "LOCAL_VERIFIED"
    assert result["aws_execution"] is False
    assert result["proof"] == "part4-stage3-pre-aws-admission-controls"


def test_workflow_permission_drift_fails_closed(tmp_path: Path) -> None:
    workflow = (ROOT / MODULE.WORKFLOW).read_text(encoding="utf-8")
    changed = workflow.replace(
        "permissions:\n  contents: read", "permissions:\n  id-token: write", 1
    )
    root = tmp_path / "repo"
    target = root / MODULE.WORKFLOW
    target.parent.mkdir(parents=True)
    target.write_text(changed, encoding="utf-8")
    contracts = root / "contracts"
    contracts.symlink_to(ROOT / "contracts", target_is_directory=True)
    github = root / ".github" / "atlas-target.json"
    github.symlink_to(ROOT / ".github" / "atlas-target.json")
    with pytest.raises(AdmissionError, match="workflow.permissions"):
        MODULE.validate(root)
