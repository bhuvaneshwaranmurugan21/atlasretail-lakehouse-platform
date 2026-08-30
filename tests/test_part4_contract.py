from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from atlasretail.part4_contract import (
    FORBIDDEN_REGION,
    ContractError,
    canonical_sha256,
    load_json_object,
    validate_part4_contract,
    validate_part4_contract_file,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "contracts" / "part4" / "run-contract.json"
TARGET_PATH = ROOT / ".github" / "atlas-target.json"


def contract() -> dict[str, Any]:
    return load_json_object(CONTRACT_PATH)


def scenario(value: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in value["scenarios"] if item["name"] == name)


def assert_rejected(value: dict[str, Any], error_path: str) -> None:
    with pytest.raises(ContractError, match=re.escape(error_path)):
        validate_part4_contract(value, repo_root=ROOT)


def test_frozen_contract_validates_and_has_exact_aggregate_bounds() -> None:
    result = validate_part4_contract_file(CONTRACT_PATH, repo_root=ROOT)

    assert result.scenario_count == 10
    assert result.step_functions_execution_count == 8
    assert result.glue_job_run_count == 6
    assert len(result.contract_sha256) == 64
    assert len(result.target_sha256) == 64
    assert result.to_dict()["result"] == "PASS"


def test_contract_digest_is_independent_of_json_formatting_and_key_order() -> None:
    value = contract()
    reordered = dict(reversed(list(value.items())))

    assert canonical_sha256(reordered) == canonical_sha256(value)


@pytest.mark.parametrize(
    ("path", "weakened", "error_path"),
    [
        (("authorization", "allowed_event"), "push", "authorization"),
        (("authorization", "execute_confirmation"), "DESTROY", "authorization"),
        (("authorization", "persist_teardown_authority_before_mutation"), False, "authorization"),
        (("workload", "order_count", "default"), 1000, "workload"),
        (("workload", "order_count", "maximum"), 2001, "workload"),
        (("cost", "run_ceiling_usd", "maximum"), 10, "cost"),
        (("cost", "fresh_account_plan_or_owner_attestation_required"), False, "cost"),
        (("target_binding", "forbidden_regions"), [], "target_binding.forbidden_regions"),
        (("target_binding", "required_values", "aws_region"), FORBIDDEN_REGION, "target_binding"),
        (("teardown", "always_run_after_admitted_mutation"), False, "teardown"),
        (("teardown", "lease_release_requires_clean_teardown"), False, "teardown"),
        (("claim_policy", "aws_verified_requires_complete_evidence"), False, "claim_policy"),
        (("claim_policy", "production_claim"), True, "claim_policy"),
        (("evidence", "artifact_upload_required"), False, "evidence.artifact_upload_required"),
    ],
)
def test_contract_rejects_weakened_bounds(
    path: tuple[str, ...], weakened: object, error_path: str
) -> None:
    value = copy.deepcopy(contract())
    cursor: dict[str, Any] = value
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = weakened

    assert_rejected(value, error_path)


def test_contract_rejects_a_missing_required_scenario() -> None:
    value = copy.deepcopy(contract())
    value["scenarios"] = [item for item in value["scenarios"] if item["name"] != "tamper"]

    assert_rejected(value, "scenario names")


def test_contract_rejects_a_generic_failure_without_semantic_signal() -> None:
    value = copy.deepcopy(contract())
    scenario(value, "financial")["failure_signal"] = None

    assert_rejected(value, "scenarios.financial")


def test_contract_rejects_recovery_with_a_substitute_identity() -> None:
    value = copy.deepcopy(contract())
    scenario(value, "recovery")["required_assertions"].remove("SAME_GENERATION_ID_AS_FAILURE")

    assert_rejected(value, "scenarios.recovery")


def test_contract_rejects_hardcoded_mutable_runtime_facts() -> None:
    value = copy.deepcopy(contract())
    value["github_run_id"] = 123456789

    assert_rejected(value, "top-level keys")


def test_contract_rejects_target_content_drift(tmp_path: Path) -> None:
    target = json.loads(TARGET_PATH.read_text(encoding="utf-8"))
    target["run_ceiling_usd"] = 10
    copied_target = tmp_path / ".github" / "atlas-target.json"
    copied_target.parent.mkdir(parents=True)
    copied_target.write_text(json.dumps(target, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ContractError, match="target_binding.sha256"):
        validate_part4_contract(contract(), repo_root=tmp_path)


def test_cli_emits_machine_readable_contract_identity() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/validate_part4_contract.py"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    output = json.loads(completed.stdout)
    assert output["result"] == "PASS"
    assert output["scenario_count"] == 10
    assert output["step_functions_execution_count"] == 8
    assert output["glue_job_run_count"] == 6
