"""Adversarial checks for the Part 5 Stage 2 completion-gap baseline."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from atlasretail.canonical import digest
from release.part5.stage1.completion_contract import COMPLETION_GATES, ORIGINAL_OBJECTIVES
from release.part5.stage2.evidence_traceability import (
    EVIDENCE,
    SCHEMA,
    TraceabilityError,
    build_traceability,
    load_traceability,
    validate_publication_authority,
    validate_traceability,
)
from release.part5.stage2.validate_controls import (
    ControlsError,
    validate,
    validate_schema,
)

ROOT = Path(__file__).parents[1]
CONTROLS_MERGE_COMMIT = "a" * 40
CONTROLS_MAIN_CI_RUN_ID = "33410000000"


def resign(receipt: dict[str, Any]) -> None:
    payload = dict(receipt)
    payload.pop("receipt_sha256")
    receipt["receipt_sha256"] = digest(payload)


def test_traceability_is_deterministic_complete_and_fail_closed() -> None:
    first = build_traceability(CONTROLS_MERGE_COMMIT, CONTROLS_MAIN_CI_RUN_ID, ROOT)
    second = build_traceability(CONTROLS_MERGE_COMMIT, CONTROLS_MAIN_CI_RUN_ID, ROOT)
    assert first == second
    assert [row["objective"] for row in first["objective_traceability"]] == list(
        ORIGINAL_OBJECTIVES
    )
    assert [row["gate"] for row in first["gate_traceability"]] == list(COMPLETION_GATES)
    assert len(first["gaps"]) == 6
    assert all(row["blocking"] for row in first["gaps"])
    assert first["project_completion"]["project_complete"] is False
    assert first["aws_execution"] is False
    validate_traceability(first, ROOT)


def test_traceability_preserves_expected_status_distribution() -> None:
    receipt = build_traceability(CONTROLS_MERGE_COMMIT, CONTROLS_MAIN_CI_RUN_ID, ROOT)
    statuses = [row["status"] for row in receipt["gate_traceability"]]
    assert statuses.count("PRESERVED_PASS") == 6
    assert statuses.count("CURRENT_PASS_RECHECK_REQUIRED") == 3
    assert statuses.count("PARTIAL") == 1
    assert statuses.count("OPEN") == 2


def test_traceability_rejects_missing_gate_even_when_resigned() -> None:
    receipt = deepcopy(build_traceability(CONTROLS_MERGE_COMMIT, CONTROLS_MAIN_CI_RUN_ID, ROOT))
    receipt["gate_traceability"].pop()
    resign(receipt)
    with pytest.raises(TraceabilityError, match="values differ"):
        validate_traceability(receipt, ROOT)


def test_traceability_rejects_status_promotion_even_when_resigned() -> None:
    receipt = deepcopy(build_traceability(CONTROLS_MERGE_COMMIT, CONTROLS_MAIN_CI_RUN_ID, ROOT))
    handoff = next(
        row for row in receipt["gate_traceability"] if row["gate"] == "operational_handoff_verified"
    )
    handoff["status"] = "PRESERVED_PASS"
    handoff["gap_id"] = None
    resign(receipt)
    with pytest.raises(TraceabilityError, match="values differ"):
        validate_traceability(receipt, ROOT)


def test_traceability_rejects_removed_gap_even_when_resigned() -> None:
    receipt = deepcopy(build_traceability(CONTROLS_MERGE_COMMIT, CONTROLS_MAIN_CI_RUN_ID, ROOT))
    receipt["gaps"] = [row for row in receipt["gaps"] if row["gap_id"] != "P5-GAP-006"]
    resign(receipt)
    with pytest.raises(TraceabilityError, match="values differ"):
        validate_traceability(receipt, ROOT)


def test_traceability_rejects_completion_inflation_even_when_resigned() -> None:
    receipt = deepcopy(build_traceability(CONTROLS_MERGE_COMMIT, CONTROLS_MAIN_CI_RUN_ID, ROOT))
    receipt["project_completion"]["project_complete"] = True
    receipt["project_completion"]["remaining_work_required"] = False
    resign(receipt)
    with pytest.raises(TraceabilityError, match="values differ"):
        validate_traceability(receipt, ROOT)


def test_traceability_rejects_authority_mutation_even_when_resigned() -> None:
    receipt = deepcopy(build_traceability(CONTROLS_MERGE_COMMIT, CONTROLS_MAIN_CI_RUN_ID, ROOT))
    receipt["authority_file_sha256"]["part4-closure"] = "0" * 64
    resign(receipt)
    with pytest.raises(TraceabilityError, match="values differ"):
        validate_traceability(receipt, ROOT)


def test_traceability_rejects_unknown_nested_keys() -> None:
    receipt = build_traceability(CONTROLS_MERGE_COMMIT, CONTROLS_MAIN_CI_RUN_ID, ROOT)
    receipt["gate_traceability"][0]["unexpected"] = True
    resign(receipt)
    with pytest.raises(TraceabilityError, match="values differ"):
        validate_traceability(receipt, ROOT)


def test_traceability_rejects_digest_mutation() -> None:
    receipt = build_traceability(CONTROLS_MERGE_COMMIT, CONTROLS_MAIN_CI_RUN_ID, ROOT)
    receipt["receipt_sha256"] = "0" * 64
    with pytest.raises(TraceabilityError, match="digest differs"):
        validate_traceability(receipt, ROOT)


@pytest.mark.parametrize(
    ("commit", "run_id", "message"),
    (
        ("A" * 40, CONTROLS_MAIN_CI_RUN_ID, "controls merge commit is invalid"),
        (CONTROLS_MERGE_COMMIT, "0", "controls main CI run ID is invalid"),
    ),
)
def test_traceability_rejects_invalid_publication_identifiers(
    commit: str,
    run_id: str,
    message: str,
) -> None:
    with pytest.raises(TraceabilityError, match=message):
        build_traceability(commit, run_id, ROOT)


def test_publication_authority_requires_a_real_post_stage1_commit() -> None:
    receipt = build_traceability(CONTROLS_MERGE_COMMIT, CONTROLS_MAIN_CI_RUN_ID, ROOT)
    with pytest.raises(TraceabilityError, match="absent from repository history"):
        validate_publication_authority(receipt, ROOT)


def test_gap_schema_cannot_permit_unknown_properties(tmp_path: Path) -> None:
    schema = json.loads((ROOT / SCHEMA).read_text(encoding="utf-8"))
    schema["additionalProperties"] = True
    path = tmp_path / "completion-gap.schema.json"
    path.write_text(json.dumps(schema), encoding="utf-8")
    with pytest.raises(ControlsError, match="permits unknown keys"):
        validate_schema(path)


def test_stage2_controls_are_deterministic_and_preserve_non_completion() -> None:
    first = validate(ROOT)
    second = validate(ROOT)
    assert first == second
    assert first["result"] == "PASS"
    assert first["state"] == "TRACEABILITY_CONTROLS_READY"
    assert first["project_complete"] is False
    assert first["aws_execution"] is False
    assert first["objective_count"] == 7
    assert first["gate_count"] == 12
    assert first["gap_count"] == 6


def test_committed_receipt_is_verified_when_present() -> None:
    path = ROOT / EVIDENCE
    if path.is_file():
        validate_publication_authority(load_traceability(path), ROOT)
