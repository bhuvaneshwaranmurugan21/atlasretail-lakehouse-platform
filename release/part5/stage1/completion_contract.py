"""Build and validate the deterministic Part 5 completion contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from atlasretail.canonical import digest

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = Path("release/part5/stage1/completion-contract.schema.json")
CONTRACT = Path("evidence/part5/stage1/completion-contract.json")

PART4_RELEASE_COMMIT = "e9b3471b727a777d7fe1b62b3997d9aac30d0eac"
PART4_TAG_OBJECT = "eb7cc385034abb2084bce51745b43d9a51bb37ee"
PART4_RECEIPT_FILE_SHA256 = "2ee89a81694f02cde135a9e367151271825c004152f8816c53a464443d47e772"
PART4_ARCHIVE_SHA256 = "ab6be34b79bafd70d6c349a374ff8a5afe3053d696a00b93f0a3958992da670a"
PART4_POST_RELEASE_SHA256 = "f0dfd53d23cef73c100180bd3c4d838fc53b0d09dfb4604644f361ea29e568e8"
PART4_RUNTIME_SHA256 = "2e1d10c936c23637929e65589fab324c4a2602b98da283135527733ea26f1e38"
PART4_RUNTIME_SOURCE = "08559b0f48708080335282c6d59faa3826635d67"

SOURCE_EVIDENCE = (
    Path("contracts/part4/stage7-runtime-manifest.json"),
    Path("evidence/part4/stage7/completion-receipt.json"),
    Path("evidence/part4/stage8/release-receipt.json"),
    Path("release/part4/stage8/evidence-retention.json"),
)

COMPLETION_GATES = (
    "all_part5_stages_complete",
    "claim_boundaries_preserved",
    "clean_inventory_authority_preserved",
    "deterministic_recovery_authority_preserved",
    "final_main_ci_green",
    "frozen_runtime_preserved",
    "managed_workload_authority_preserved",
    "operational_handoff_verified",
    "professional_naming_verified",
    "release_integrity_preserved",
    "repository_quality_gates_green",
    "unresolved_critical_defects_absent",
)

ORIGINAL_OBJECTIVES = (
    "cross_table_consistency",
    "deterministic_failure_recovery",
    "evidence_attribution",
    "managed_aws_validation",
    "operational_handoff",
    "release_integrity",
    "repository_quality",
)


class CompletionContractError(ValueError):
    """Raised when the completion contract differs from its frozen boundary."""


def sha256(path: Path) -> str:
    """Return the SHA-256 digest of one file."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_contract(repository: Path = ROOT) -> dict[str, Any]:
    """Build the exact Stage 1 completion contract from immutable authorities."""

    payload: dict[str, Any] = {
        "actual_billed_cost_claim": "UNCLAIMED",
        "aws_execution": False,
        "claim_boundaries": {
            "production": "NOT_CLAIMED",
            "settled_billing": "UNCLAIMED",
            "sustained_operation": "NOT_ESTABLISHED",
        },
        "claim_level": "LOCAL_VERIFIED",
        "completion_gates": list(COMPLETION_GATES),
        "evidence_type": "part5-stage1-completion-contract",
        "original_objectives": list(ORIGINAL_OBJECTIVES),
        "part": 5,
        "predecessor": {
            "archive_sha256": PART4_ARCHIVE_SHA256,
            "clean_inventory_run_id": "33364428199",
            "post_release_verification_sha256": PART4_POST_RELEASE_SHA256,
            "recovery_run_id": "33328391707",
            "release_commit": PART4_RELEASE_COMMIT,
            "release_receipt_file_sha256": PART4_RECEIPT_FILE_SHA256,
            "tag": "v0.1.0",
            "tag_object": PART4_TAG_OBJECT,
            "tag_type": "ANNOTATED",
            "workload_run_id": "33329861907",
        },
        "project": "AtlasRetail",
        "project_completion": {
            "all_part5_stages_complete": False,
            "part5_completion_equals_project_completion": True,
            "project_complete": False,
            "remaining_work_required": True,
            "stage1_completion_claim": "CONTRACT_ONLY",
        },
        "runtime_equivalence": {
            "baseline_source_commit": PART4_RUNTIME_SOURCE,
            "file_count": 107,
            "files_sha256": PART4_RUNTIME_SHA256,
            "result": "PASS",
        },
        "schema_sha256": sha256(repository / SCHEMA),
        "schema_version": "1.0",
        "source_evidence_sha256": {
            path.as_posix(): sha256(repository / path) for path in SOURCE_EVIDENCE
        },
        "stage": 1,
        "state": "CONTRACT_FROZEN",
    }
    return {**payload, "contract_sha256": digest(payload)}


def validate_contract(contract: dict[str, Any], repository: Path = ROOT) -> None:
    """Fail closed when any digest, authority, objective, or claim boundary changes."""

    expected = build_contract(repository)
    if set(contract) != set(expected):
        raise CompletionContractError("contract keys differ")
    payload = dict(contract)
    supplied_digest = payload.pop("contract_sha256")
    if supplied_digest != digest(payload):
        raise CompletionContractError("contract digest differs")
    expected_payload = dict(expected)
    expected_payload.pop("contract_sha256")
    if payload != expected_payload:
        raise CompletionContractError("contract values differ")


def load_contract(path: Path) -> dict[str, Any]:
    """Load one JSON contract and reject non-object content."""

    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CompletionContractError("contract is not an object")
    return value
