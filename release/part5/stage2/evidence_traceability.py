"""Build and validate the deterministic Part 5 Stage 2 completion-gap baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, NoReturn

from atlasretail.canonical import digest
from release.part5.stage1.completion_contract import (
    CONTRACT,
    PART4_RELEASE_COMMIT,
    CompletionContractError,
    load_contract,
    validate_contract,
)

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = Path("release/part5/stage2/completion-gap.schema.json")
EVIDENCE = Path("evidence/part5/stage2/completion-gap.json")
STAGE1_MERGE_COMMIT = "9b695751ebc0c44ea187f8ceac442fbdbb12fbad"

STATUS_VALUES = {
    "CURRENT_PASS_RECHECK_REQUIRED",
    "OPEN",
    "PARTIAL",
    "PRESERVED_PASS",
}
SEVERITY_VALUES = {"CRITICAL", "HIGH", "LOW", "MEDIUM"}

AUTHORITY_FILES = {
    "part4-closure": Path("evidence/part4/stage7/completion-receipt.json"),
    "part4-release": Path("evidence/part4/stage8/release-receipt.json"),
    "part5-completion-contract": CONTRACT,
}

OBJECTIVE_STATUS = {
    "cross_table_consistency": "PRESERVED_PASS",
    "deterministic_failure_recovery": "PRESERVED_PASS",
    "evidence_attribution": "PRESERVED_PASS",
    "managed_aws_validation": "PRESERVED_PASS",
    "operational_handoff": "PARTIAL",
    "release_integrity": "PRESERVED_PASS",
    "repository_quality": "CURRENT_PASS_RECHECK_REQUIRED",
}

OBJECTIVE_GATES = {
    "cross_table_consistency": ["managed_workload_authority_preserved"],
    "deterministic_failure_recovery": ["deterministic_recovery_authority_preserved"],
    "evidence_attribution": ["claim_boundaries_preserved", "release_integrity_preserved"],
    "managed_aws_validation": [
        "clean_inventory_authority_preserved",
        "managed_workload_authority_preserved",
    ],
    "operational_handoff": ["operational_handoff_verified"],
    "release_integrity": ["frozen_runtime_preserved", "release_integrity_preserved"],
    "repository_quality": [
        "professional_naming_verified",
        "repository_quality_gates_green",
        "unresolved_critical_defects_absent",
    ],
}

OBJECTIVE_AUTHORITIES = {
    "cross_table_consistency": ["part4-closure"],
    "deterministic_failure_recovery": ["part4-closure"],
    "evidence_attribution": [
        "part4-closure",
        "part4-release",
        "part5-completion-contract",
    ],
    "managed_aws_validation": ["part4-closure"],
    "operational_handoff": ["part4-release"],
    "release_integrity": ["part4-release", "part5-completion-contract"],
    "repository_quality": ["part5-completion-contract"],
}

GATE_STATUS = {
    "all_part5_stages_complete": "OPEN",
    "claim_boundaries_preserved": "PRESERVED_PASS",
    "clean_inventory_authority_preserved": "PRESERVED_PASS",
    "deterministic_recovery_authority_preserved": "PRESERVED_PASS",
    "final_main_ci_green": "OPEN",
    "frozen_runtime_preserved": "PRESERVED_PASS",
    "managed_workload_authority_preserved": "PRESERVED_PASS",
    "operational_handoff_verified": "PARTIAL",
    "professional_naming_verified": "CURRENT_PASS_RECHECK_REQUIRED",
    "release_integrity_preserved": "PRESERVED_PASS",
    "repository_quality_gates_green": "CURRENT_PASS_RECHECK_REQUIRED",
    "unresolved_critical_defects_absent": "CURRENT_PASS_RECHECK_REQUIRED",
}

GATE_AUTHORITIES = {
    "all_part5_stages_complete": [],
    "claim_boundaries_preserved": ["part5-completion-contract"],
    "clean_inventory_authority_preserved": ["part4-closure"],
    "deterministic_recovery_authority_preserved": ["part4-closure"],
    "final_main_ci_green": [],
    "frozen_runtime_preserved": ["part4-closure", "part5-completion-contract"],
    "managed_workload_authority_preserved": ["part4-closure"],
    "operational_handoff_verified": ["part4-release"],
    "professional_naming_verified": ["part5-completion-contract"],
    "release_integrity_preserved": ["part4-release", "part5-completion-contract"],
    "repository_quality_gates_green": ["part5-completion-contract"],
    "unresolved_critical_defects_absent": ["part5-completion-contract"],
}

GAPS = (
    (
        "P5-GAP-001",
        "all_part5_stages_complete",
        "CRITICAL",
        "validated completion receipts for every Part 5 stage",
    ),
    (
        "P5-GAP-002",
        "final_main_ci_green",
        "HIGH",
        "successful main-branch CI bound to the final project commit",
    ),
    (
        "P5-GAP-003",
        "operational_handoff_verified",
        "HIGH",
        "rehearsed handoff receipt covering operation, recovery, and escalation",
    ),
    (
        "P5-GAP-004",
        "professional_naming_verified",
        "HIGH",
        "repository-wide naming-policy scan at the completion candidate",
    ),
    (
        "P5-GAP-005",
        "repository_quality_gates_green",
        "HIGH",
        "source-exact lint, format, type, test, and control-validation results",
    ),
    (
        "P5-GAP-006",
        "unresolved_critical_defects_absent",
        "CRITICAL",
        "triaged defect inventory with no unresolved critical finding",
    ),
)

GAP_BY_GATE = {gate: gap_id for gap_id, gate, _severity, _evidence in GAPS}


class TraceabilityError(ValueError):
    """Raised when the Stage 2 baseline is incomplete or inflated."""


def fail(message: str) -> NoReturn:
    raise TraceabilityError(message)


def sha256(path: Path) -> str:
    """Return the SHA-256 digest of one file."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_stage1(repository: Path) -> dict[str, Any]:
    contract = load_contract(repository / CONTRACT)
    try:
        validate_contract(contract, repository)
    except CompletionContractError as error:
        raise TraceabilityError(f"Stage 1 admission failed: {error}") from error
    return contract


def _validate_identifier(value: str, pattern: str, description: str) -> None:
    if re.fullmatch(pattern, value) is None:
        fail(f"{description} is invalid")


def build_traceability(
    controls_merge_commit: str,
    controls_main_ci_run_id: str,
    repository: Path = ROOT,
) -> dict[str, Any]:
    """Build the exact Stage 2 objective, gate, and open-gap mapping."""

    _validate_identifier(
        controls_merge_commit,
        r"[0-9a-f]{40}",
        "controls merge commit",
    )
    _validate_identifier(controls_main_ci_run_id, r"[1-9][0-9]*", "controls main CI run ID")
    contract = _load_stage1(repository)
    objectives = list(contract["original_objectives"])
    gates = list(contract["completion_gates"])
    if not (
        set(objectives)
        == set(OBJECTIVE_STATUS)
        == set(OBJECTIVE_GATES)
        == set(OBJECTIVE_AUTHORITIES)
    ):
        fail("objective coverage differs from the Stage 1 contract")
    if not set(gates) == set(GATE_STATUS) == set(GATE_AUTHORITIES):
        fail("gate coverage differs from the Stage 1 contract")

    objective_traceability = [
        {
            "authority_ids": OBJECTIVE_AUTHORITIES[objective],
            "gate_ids": OBJECTIVE_GATES[objective],
            "objective": objective,
            "status": OBJECTIVE_STATUS[objective],
        }
        for objective in objectives
    ]
    gate_traceability = [
        {
            "authority_ids": GATE_AUTHORITIES[gate],
            "gap_id": GAP_BY_GATE.get(gate),
            "gate": gate,
            "status": GATE_STATUS[gate],
        }
        for gate in gates
    ]
    gaps = [
        {
            "blocking": True,
            "gap_id": gap_id,
            "gate": gate,
            "required_closure_evidence": evidence,
            "severity": severity,
        }
        for gap_id, gate, severity, evidence in GAPS
    ]
    payload: dict[str, Any] = {
        "actual_billed_cost_claim": "UNCLAIMED",
        "authority_file_sha256": {
            authority_id: sha256(repository / path)
            for authority_id, path in AUTHORITY_FILES.items()
        },
        "aws_execution": False,
        "claim_boundaries": contract["claim_boundaries"],
        "claim_level": "LOCAL_VERIFIED",
        "controls_authority": {
            "main_ci_run_id": controls_main_ci_run_id,
            "merge_commit": controls_merge_commit,
        },
        "evidence_type": "part5-stage2-completion-gap-baseline",
        "gaps": gaps,
        "gate_traceability": gate_traceability,
        "objective_traceability": objective_traceability,
        "part": 5,
        "project": "AtlasRetail",
        "project_completion": {
            "all_part5_stages_complete": False,
            "project_complete": False,
            "remaining_work_required": True,
        },
        "schema_sha256": sha256(repository / SCHEMA),
        "schema_version": "1.0",
        "stage": 2,
        "stage1_contract_sha256": contract["contract_sha256"],
        "state": "GAP_BASELINE_RECORDED",
    }
    return {**payload, "receipt_sha256": digest(payload)}


def validate_traceability(receipt: dict[str, Any], repository: Path = ROOT) -> None:
    """Fail closed on missing coverage, status promotion, or claim inflation."""

    controls = receipt.get("controls_authority")
    if not isinstance(controls, dict):
        fail("controls authority is absent")
    merge_commit = controls.get("merge_commit")
    main_ci_run_id = controls.get("main_ci_run_id")
    if not isinstance(merge_commit, str) or not isinstance(main_ci_run_id, str):
        fail("controls authority identifiers are absent")
    expected = build_traceability(merge_commit, main_ci_run_id, repository)
    if set(receipt) != set(expected):
        fail("receipt keys differ")
    payload = dict(receipt)
    supplied_digest = payload.pop("receipt_sha256")
    if supplied_digest != digest(payload):
        fail("receipt digest differs")
    expected_payload = dict(expected)
    expected_payload.pop("receipt_sha256")
    if payload != expected_payload:
        fail("receipt values differ")

    gate_rows = receipt["gate_traceability"]
    statuses = {row["status"] for row in gate_rows}
    if not statuses <= STATUS_VALUES:
        fail("gate status vocabulary differs")
    gap_rows = receipt["gaps"]
    if {row["severity"] for row in gap_rows} - SEVERITY_VALUES:
        fail("gap severity vocabulary differs")
    non_preserved = {row["gate"] for row in gate_rows if row["status"] != "PRESERVED_PASS"}
    gap_gates = {row["gate"] for row in gap_rows}
    if non_preserved != gap_gates:
        fail("open or recheck gates do not have exact gap coverage")
    authority_ids = set(receipt["authority_file_sha256"])
    referenced = {
        authority
        for row in [*receipt["objective_traceability"], *gate_rows]
        for authority in row["authority_ids"]
    }
    if referenced != authority_ids:
        fail("traceability rows do not reference the exact authority set")


def validate_publication_authority(receipt: dict[str, Any], repository: Path = ROOT) -> None:
    """Require the recorded controls merge to exist in this Stage 2 evidence history."""

    validate_traceability(receipt, repository)
    merge_commit = receipt["controls_authority"]["merge_commit"]
    exists = subprocess.run(
        ["git", "cat-file", "-e", f"{merge_commit}^{{commit}}"],
        cwd=repository,
        check=False,
        capture_output=True,
    )
    if exists.returncode != 0:
        fail("controls merge commit is absent from repository history")
    if merge_commit in {STAGE1_MERGE_COMMIT, PART4_RELEASE_COMMIT}:
        fail("controls merge commit does not identify the Stage 2 controls merge")
    for ancestor, descendant, message in (
        (STAGE1_MERGE_COMMIT, merge_commit, "controls merge does not descend from Stage 1"),
        (merge_commit, "HEAD", "receipt history does not descend from the controls merge"),
    ):
        completed = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=repository,
            check=False,
            capture_output=True,
        )
        if completed.returncode != 0:
            fail(message)


def load_traceability(path: Path) -> dict[str, Any]:
    """Load one receipt and reject non-object content."""

    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        fail("receipt is not an object")
    return value


def write_traceability(path: Path, receipt: dict[str, Any]) -> None:
    """Write canonical human-readable JSON for review and byte comparison."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--controls-merge-commit", required=True)
    build.add_argument("--controls-main-ci-run-id", required=True)
    build.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "build":
            receipt = build_traceability(
                args.controls_merge_commit,
                args.controls_main_ci_run_id,
                ROOT,
            )
            write_traceability(args.output, receipt)
        else:
            validate_publication_authority(load_traceability(args.receipt), ROOT)
    except (OSError, TraceabilityError, subprocess.SubprocessError) as error:
        print(f"Part 5 Stage 2 traceability rejected: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
