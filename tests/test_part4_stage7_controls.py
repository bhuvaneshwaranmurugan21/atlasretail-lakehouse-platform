"""Adversarial checks for the deterministic Stage 7 readiness gate."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_part4_stage7_controls", ROOT / "scripts/validate_part4_stage7_controls.py"
)
assert SPEC and SPEC.loader
CONTROLS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTROLS)


def test_repository_stage7_controls_pass_deterministically() -> None:
    first = CONTROLS.validate(ROOT)
    second = CONTROLS.validate(ROOT)
    assert first == second
    assert first["result"] == "PASS"
    assert first["claim_level"] == "LOCAL_VERIFIED"
    assert first["aws_execution"] is False
    assert first["production_claim"] is False
    assert first["actual_billed_cost_claim"] == "UNCLAIMED"
    assert first["completion_published"] is True
    assert all(first["checks"].values())


def test_closure_schema_cannot_permit_unknown_properties(tmp_path: Path) -> None:
    schema = json.loads((ROOT / CONTROLS.CLOSURE_SCHEMA).read_text(encoding="utf-8"))
    schema["additionalProperties"] = True
    path = tmp_path / "closure.schema.json"
    path.write_text(json.dumps(schema), encoding="utf-8")
    with pytest.raises(CONTROLS.ControlsError, match="permits unknown keys"):
        CONTROLS.validate_schema(path)


def test_preflight_cannot_gain_workload_behavior(tmp_path: Path) -> None:
    source = ROOT / CONTROLS.PREFLIGHT
    changed = source.read_text(encoding="utf-8").replace(
        "set -euo pipefail", "set -euo pipefail\n          aws glue start-job-run", 1
    )
    path = tmp_path / "preflight.yml"
    path.write_text(changed, encoding="utf-8")
    with pytest.raises(CONTROLS.ControlsError, match="mutation or workload behavior"):
        CONTROLS.validate_preflight(path)


def test_credit_amount_cannot_ignore_estimated_usage(tmp_path: Path) -> None:
    credit = json.loads((ROOT / CONTROLS.CREDIT).read_text(encoding="utf-8"))
    credit["verified_remaining_usd"] = 120
    path = tmp_path / "credit.json"
    path.write_text(json.dumps(credit), encoding="utf-8")
    with pytest.raises(CONTROLS.ControlsError, match="not conservative"):
        CONTROLS.validate_credit(path)


def test_runtime_manifest_digest_cannot_change(tmp_path: Path) -> None:
    manifest = json.loads((ROOT / CONTROLS.RUNTIME_MANIFEST).read_text(encoding="utf-8"))
    manifest["expected_files_sha256"] = "0" * 64
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CONTROLS.ControlsError, match="runtime bytes differ"):
        CONTROLS.validate_runtime_manifest(path)
