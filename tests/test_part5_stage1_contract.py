"""Adversarial checks for the Part 5 Stage 1 completion contract."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from atlasretail.canonical import digest
from release.part5.stage1.completion_contract import (
    CONTRACT,
    PART4_RELEASE_COMMIT,
    PART4_RUNTIME_SHA256,
    PART4_TAG_OBJECT,
    SCHEMA,
    CompletionContractError,
    build_contract,
    load_contract,
    validate_contract,
)
from release.part5.stage1.validate_controls import ControlsError, validate, validate_schema

ROOT = Path(__file__).parents[1]


def resign(contract: dict[str, Any]) -> None:
    payload = dict(contract)
    payload.pop("contract_sha256")
    contract["contract_sha256"] = digest(payload)


def test_contract_is_deterministic_committed_and_valid() -> None:
    first = build_contract(ROOT)
    second = build_contract(ROOT)
    committed = load_contract(ROOT / CONTRACT)
    assert first == second == committed
    validate_contract(committed, ROOT)


def test_contract_binds_exact_part4_authorities() -> None:
    contract = build_contract(ROOT)
    assert contract["predecessor"]["release_commit"] == PART4_RELEASE_COMMIT
    assert contract["predecessor"]["tag_object"] == PART4_TAG_OBJECT
    assert contract["predecessor"]["workload_run_id"] == "33329861907"
    assert contract["predecessor"]["recovery_run_id"] == "33328391707"
    assert contract["predecessor"]["clean_inventory_run_id"] == "33364428199"
    assert contract["runtime_equivalence"]["files_sha256"] == PART4_RUNTIME_SHA256


def test_contract_rejects_runtime_drift() -> None:
    contract = deepcopy(build_contract(ROOT))
    contract["runtime_equivalence"]["file_count"] = 108
    resign(contract)
    with pytest.raises(CompletionContractError, match="values differ"):
        validate_contract(contract, ROOT)


def test_contract_rejects_claim_inflation() -> None:
    contract = deepcopy(build_contract(ROOT))
    contract["claim_boundaries"]["production"] = "CLAIMED"
    resign(contract)
    with pytest.raises(CompletionContractError, match="values differ"):
        validate_contract(contract, ROOT)


def test_contract_rejects_early_project_completion() -> None:
    contract = deepcopy(build_contract(ROOT))
    contract["project_completion"]["project_complete"] = True
    contract["project_completion"]["remaining_work_required"] = False
    resign(contract)
    with pytest.raises(CompletionContractError, match="values differ"):
        validate_contract(contract, ROOT)


def test_contract_rejects_unknown_keys() -> None:
    contract = build_contract(ROOT)
    contract["unexpected"] = True
    resign(contract)
    with pytest.raises(CompletionContractError, match="keys differ"):
        validate_contract(contract, ROOT)


def test_contract_rejects_digest_mutation() -> None:
    contract = build_contract(ROOT)
    contract["contract_sha256"] = "0" * 64
    with pytest.raises(CompletionContractError, match="digest differs"):
        validate_contract(contract, ROOT)


def test_completion_schema_cannot_permit_unknown_properties(tmp_path: Path) -> None:
    schema = json.loads((ROOT / SCHEMA).read_text(encoding="utf-8"))
    schema["additionalProperties"] = True
    path = tmp_path / "completion-contract.schema.json"
    path.write_text(json.dumps(schema), encoding="utf-8")
    with pytest.raises(ControlsError, match="permits unknown keys"):
        validate_schema(path)


def test_stage1_controls_are_deterministic_and_preserve_runtime() -> None:
    first = validate(ROOT)
    second = validate(ROOT)
    assert first == second
    assert first["result"] == "PASS"
    assert first["state"] == "CONTRACT_FROZEN"
    assert first["project_complete"] is False
    assert first["aws_execution"] is False
    assert first["runtime_equivalence"]["file_count"] == 107
