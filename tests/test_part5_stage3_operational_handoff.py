"""Adversarial checks for the Part 5 Stage 3 operational handoff."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from atlasretail.canonical import digest
from release.part5.stage3.operational_handoff import (
    CATALOG,
    EVIDENCE,
    SCHEMA,
    HandoffError,
    build_handoff,
    load_handoff,
    validate_catalog,
    validate_handoff,
    validate_publication_authority,
)
from release.part5.stage3.validate_controls import (
    ControlsError,
    validate,
    validate_schema,
)

ROOT = Path(__file__).parents[1]
CONTROLS_MERGE_COMMIT = "a" * 40
CONTROLS_MAIN_CI_RUN_ID = "33420000000"


def resign(receipt: dict[str, Any]) -> None:
    payload = dict(receipt)
    payload.pop("receipt_sha256")
    receipt["receipt_sha256"] = digest(payload)


def build() -> dict[str, Any]:
    return build_handoff(CONTROLS_MERGE_COMMIT, CONTROLS_MAIN_CI_RUN_ID, ROOT)


def test_handoff_is_deterministic_complete_and_fail_closed() -> None:
    first = build()
    second = build()
    assert first == second
    assert [row["scenario_id"] for row in first["rehearsals"]] == [
        "normal-operation",
        "authority-bound-recovery",
        "lease-only-recovery",
        "stop-and-escalate",
    ]
    assert [row["category"] for row in first["rehearsals"]].count("OPERATION") == 1
    assert [row["category"] for row in first["rehearsals"]].count("RECOVERY") == 2
    assert [row["category"] for row in first["rehearsals"]].count("ESCALATION") == 1
    validate_handoff(first, ROOT)


def test_handoff_closes_only_operational_gap() -> None:
    receipt = build()
    assert receipt["closed_gap_ids"] == ["P5-GAP-003"]
    assert receipt["remaining_gap_ids"] == [
        "P5-GAP-001",
        "P5-GAP-002",
        "P5-GAP-004",
        "P5-GAP-005",
        "P5-GAP-006",
    ]
    assert receipt["project_completion"]["project_complete"] is False


def test_handoff_rejects_missing_scenario_even_when_resigned() -> None:
    receipt = deepcopy(build())
    receipt["rehearsals"].pop()
    resign(receipt)
    with pytest.raises(HandoffError, match="values differ"):
        validate_handoff(receipt, ROOT)


def test_handoff_rejects_decision_change_even_when_resigned() -> None:
    receipt = deepcopy(build())
    receipt["rehearsals"][1]["decision"] = "RETRY"
    resign(receipt)
    with pytest.raises(HandoffError, match="values differ"):
        validate_handoff(receipt, ROOT)


def test_handoff_rejects_removed_prohibition_even_when_resigned() -> None:
    receipt = deepcopy(build())
    receipt["rehearsals"][3]["prohibited_actions"].pop()
    resign(receipt)
    with pytest.raises(HandoffError, match="values differ"):
        validate_handoff(receipt, ROOT)


def test_catalog_rejects_wrong_recovery_route() -> None:
    catalog = json.loads((ROOT / CATALOG).read_text(encoding="utf-8"))
    catalog["scenarios"][1]["authority_checks"][0]["path"] = (
        ".github/workflows/aws-bounded-lab-lease-recovery.yml"
    )
    with pytest.raises(HandoffError, match="authority checks differ"):
        validate_catalog(catalog, ROOT)


def test_catalog_rejects_automatic_retry_permission() -> None:
    catalog = json.loads((ROOT / CATALOG).read_text(encoding="utf-8"))
    catalog["scenarios"][3]["prohibited_actions"].remove("retry automatically")
    with pytest.raises(HandoffError, match="prohibited actions differ"):
        validate_catalog(catalog, ROOT)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("aws_execution", True),
        ("closed_gap_ids", ["P5-GAP-003", "P5-GAP-005"]),
        ("remaining_gap_ids", ["P5-GAP-001"]),
    ),
)
def test_handoff_rejects_claim_or_gap_inflation_when_resigned(field: str, value: object) -> None:
    receipt = deepcopy(build())
    receipt[field] = value
    resign(receipt)
    with pytest.raises(HandoffError, match="values differ"):
        validate_handoff(receipt, ROOT)


def test_handoff_rejects_project_completion_inflation_when_resigned() -> None:
    receipt = deepcopy(build())
    receipt["project_completion"]["project_complete"] = True
    receipt["project_completion"]["remaining_work_required"] = False
    resign(receipt)
    with pytest.raises(HandoffError, match="values differ"):
        validate_handoff(receipt, ROOT)


def test_handoff_rejects_digest_mutation() -> None:
    receipt = build()
    receipt["receipt_sha256"] = "0" * 64
    with pytest.raises(HandoffError, match="digest differs"):
        validate_handoff(receipt, ROOT)


@pytest.mark.parametrize(
    ("commit", "run_id", "message"),
    (
        ("A" * 40, CONTROLS_MAIN_CI_RUN_ID, "controls merge commit is invalid"),
        (CONTROLS_MERGE_COMMIT, "0", "controls main CI run ID is invalid"),
    ),
)
def test_handoff_rejects_invalid_publication_identifiers(
    commit: str, run_id: str, message: str
) -> None:
    with pytest.raises(HandoffError, match=message):
        build_handoff(commit, run_id, ROOT)


def test_publication_authority_requires_real_stage3_commit() -> None:
    with pytest.raises(HandoffError, match="absent from repository history"):
        validate_publication_authority(build(), ROOT)


def test_handoff_schema_cannot_permit_unknown_properties(tmp_path: Path) -> None:
    schema = json.loads((ROOT / SCHEMA).read_text(encoding="utf-8"))
    schema["additionalProperties"] = True
    path = tmp_path / "operational-handoff.schema.json"
    path.write_text(json.dumps(schema), encoding="utf-8")
    with pytest.raises(ControlsError, match="permits unknown keys"):
        validate_schema(path)


def test_stage3_controls_are_deterministic_and_preserve_non_completion() -> None:
    first = validate(ROOT)
    second = validate(ROOT)
    assert first == second
    assert first["result"] == "PASS"
    assert first["state"] == "HANDOFF_CONTROLS_READY"
    assert first["project_complete"] is False
    assert first["aws_execution"] is False
    assert first["rehearsal_count"] == 4
    assert first["closed_gap_ids"] == ["P5-GAP-003"]


def test_committed_receipt_is_verified_when_present() -> None:
    path = ROOT / EVIDENCE
    if path.is_file():
        validate_publication_authority(load_handoff(path), ROOT)
