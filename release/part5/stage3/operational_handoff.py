"""Build and validate the deterministic Part 5 Stage 3 operational handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, NoReturn, cast

from atlasretail.canonical import digest
from release.part5.stage1.completion_contract import CONTRACT, load_contract, validate_contract
from release.part5.stage2.evidence_traceability import (
    EVIDENCE as STAGE2_EVIDENCE,
)
from release.part5.stage2.evidence_traceability import (
    load_traceability,
)
from release.part5.stage2.evidence_traceability import (
    validate_publication_authority as validate_stage2_publication,
)

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = Path("release/part5/stage3/operational-handoff.schema.json")
CATALOG = Path("release/part5/stage3/handoff-scenarios.json")
EVIDENCE = Path("evidence/part5/stage3/operational-handoff.json")
STAGE2_MERGE_COMMIT = "78eb1f78474b1ee0d1b2f8a31bce8d1f150f2a43"

CLOSED_GAPS = ["P5-GAP-003"]
REMAINING_GAPS = [
    "P5-GAP-001",
    "P5-GAP-002",
    "P5-GAP-004",
    "P5-GAP-005",
    "P5-GAP-006",
]

EXPECTED_SCENARIOS = {
    "normal-operation": ("OPERATION", "READY_WITH_EXACT_PREREQUISITES"),
    "authority-bound-recovery": ("RECOVERY", "RECOVER_EXACT_AUTHORITY_CLEANUP_ONLY"),
    "lease-only-recovery": ("RECOVERY", "RELEASE_EXACT_PREAUTHORITY_LEASE_ONLY"),
    "stop-and-escalate": ("ESCALATION", "STOP_PRESERVE_AND_ESCALATE"),
}

REQUIRED_CHECKS = {
    "normal-operation": {
        ".github/workflows/aws-read-only-preflight.yml": {
            "workflow_dispatch:",
            "id-token: write",
            "verify_preflight.py",
        },
        ".github/workflows/aws-glue-service-probe.yml": {
            "confirm_probe:",
            "PROBE_GLUE_CREATE_DELETE",
            "probe_glue_capability.py",
        },
        ".github/workflows/aws-plan-only.yml": {
            "workflow_dispatch:",
            "verify_account_plan.py",
            "verify_budget.py",
        },
        ".github/workflows/aws-bounded-lab.yml": {
            "order_count:",
            "EXECUTE_ATLASRETAIL_PART4",
            "confirm_destroy:",
            "preflight_run_id:",
            "glue_probe_run_id:",
            "plan_run_id:",
        },
    },
    "authority-bound-recovery": {
        ".github/workflows/aws-bounded-lab-recovery.yml": {
            "failed_run_id:",
            "failed_run_attempt:",
            "failed_source_commit:",
            "RECOVER_ATLASRETAIL_PART4",
            "Recover only the exact failed attempt authority",
        },
        "docs/incidents/part4-stage6-provider-lock-recovery.md": {
            "33326519783",
            "33328391707",
            "cleanup-only",
            "UNCLAIMED",
        },
    },
    "lease-only-recovery": {
        ".github/workflows/aws-bounded-lab-lease-recovery.yml": {
            "failed_run_id:",
            "failed_run_attempt:",
            "failed_source_commit:",
            "RELEASE_ATLASRETAIL_PART4_PREAUTHORITY_LEASE",
            "Validate failed admission and lease acquisition before AWS access",
        },
        "docs/runbook.md": {
            "failed before immutable teardown authority was persisted",
            "exact live `ACQUIRED` lease with no authority",
            "If state or resources exist, stop",
        },
    },
    "stop-and-escalate": {
        "docs/runbook.md": {
            "Do not retry automatically",
            "Account-plan or service-access denial",
            "IAM authorization failure",
            "Terraform state or tagged-resource residue",
            "Manifest or business-validation failure",
            "Missing service history or evidence file",
            "Failed or skipped teardown check",
            "preserve the run and source identifiers",
            "run a new read-only preflight before another deployment",
        }
    },
}

REQUIRED_PROHIBITIONS = {
    "normal-operation": {
        "dispatch from a non-main ref",
        "reuse stale prerequisite evidence",
        "execute without teardown confirmation",
        "accept unreadable or non-empty baseline state",
    },
    "authority-bound-recovery": {
        "delete resources manually",
        "edit or replace the account lease",
        "reuse another run authority",
        "promote cleanup evidence into a workload claim",
    },
    "lease-only-recovery": {
        "release a lease when state is non-empty",
        "release a lease when resources exist",
        "perform infrastructure cleanup in the lease-only path",
        "rely on lease expiry",
    },
    "stop-and-escalate": {
        "retry automatically",
        "suppress the failed validation",
        "release an unverified lease",
        "claim success with failed or skipped teardown",
    },
}

AUTHORITY_FILES = {
    "part4-closure": Path("evidence/part4/stage7/completion-receipt.json"),
    "part4-release": Path("evidence/part4/stage8/release-receipt.json"),
    "part5-completion-contract": CONTRACT,
    "part5-gap-baseline": STAGE2_EVIDENCE,
    "evidence-retention": Path("release/part4/stage8/evidence-retention.json"),
    "handoff-scenarios": CATALOG,
    "runbook": Path("docs/runbook.md"),
    "provider-lock-incident": Path("docs/incidents/part4-stage6-provider-lock-recovery.md"),
}


class HandoffError(ValueError):
    """Raised when Stage 3 handoff authority or rehearsal coverage is incomplete."""


def fail(message: str) -> NoReturn:
    raise HandoffError(message)


def sha256(path: Path) -> str:
    """Return the SHA-256 digest of one file."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        fail(f"{path}: expected a JSON object")
    return value


def _validate_identifier(value: str, pattern: str, description: str) -> None:
    if re.fullmatch(pattern, value) is None:
        fail(f"{description} is invalid")


def _load_predecessors(repository: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    stage1 = load_contract(repository / CONTRACT)
    try:
        validate_contract(stage1, repository)
    except ValueError as error:
        raise HandoffError(f"Stage 1 admission failed: {error}") from error
    stage2 = load_traceability(repository / STAGE2_EVIDENCE)
    try:
        validate_stage2_publication(stage2, repository)
    except ValueError as error:
        raise HandoffError(f"Stage 2 admission failed: {error}") from error
    matching = [row for row in stage2["gaps"] if row["gap_id"] == "P5-GAP-003"]
    if matching != [
        {
            "blocking": True,
            "gap_id": "P5-GAP-003",
            "gate": "operational_handoff_verified",
            "required_closure_evidence": (
                "rehearsed handoff receipt covering operation, recovery, and escalation"
            ),
            "severity": "HIGH",
        }
    ]:
        fail("Stage 2 operational-handoff gap authority differs")
    return stage1, stage2


def load_catalog(path: Path) -> dict[str, Any]:
    """Load the strict scenario catalogue."""

    return _load_object(path)


def validate_catalog(catalog: dict[str, Any], repository: Path = ROOT) -> None:
    """Reject weakened scenario coverage, decisions, or prohibited actions."""

    if set(catalog) != {"schema_version", "scenarios"}:
        fail("scenario catalogue keys differ")
    if catalog["schema_version"] != "1.0":
        fail("scenario catalogue version differs")
    scenarios_value = catalog["scenarios"]
    if not isinstance(scenarios_value, list):
        fail("scenario catalogue rows are absent")
    scenarios = cast(list[dict[str, Any]], scenarios_value)
    ids = [row.get("scenario_id") for row in scenarios]
    if ids != list(EXPECTED_SCENARIOS):
        fail("scenario catalogue coverage or ordering differs")
    for row in scenarios:
        expected_keys = {
            "authority_checks",
            "category",
            "decision",
            "expected_evidence",
            "prohibited_actions",
            "scenario_id",
        }
        if set(row) != expected_keys:
            fail("scenario catalogue row keys differ")
        scenario_id = cast(str, row["scenario_id"])
        if (row["category"], row["decision"]) != EXPECTED_SCENARIOS[scenario_id]:
            fail(f"{scenario_id}: category or decision differs")
        expected_evidence = row["expected_evidence"]
        prohibited = row["prohibited_actions"]
        if not isinstance(expected_evidence, list) or not expected_evidence:
            fail(f"{scenario_id}: expected evidence is absent")
        if len(expected_evidence) != len(set(cast(list[str], expected_evidence))):
            fail(f"{scenario_id}: expected evidence is duplicated")
        if not isinstance(prohibited, list):
            fail(f"{scenario_id}: prohibited actions are absent")
        if set(cast(list[str], prohibited)) != REQUIRED_PROHIBITIONS[scenario_id]:
            fail(f"{scenario_id}: prohibited actions differ")
        checks_value = row["authority_checks"]
        if not isinstance(checks_value, list):
            fail(f"{scenario_id}: authority checks are absent")
        checks = cast(list[dict[str, Any]], checks_value)
        actual_checks: dict[str, set[str]] = {}
        for check in checks:
            if set(check) != {"path", "required_tokens"}:
                fail(f"{scenario_id}: authority check keys differ")
            relative = check["path"]
            tokens = check["required_tokens"]
            if not isinstance(relative, str) or not isinstance(tokens, list):
                fail(f"{scenario_id}: authority check values differ")
            actual_checks[relative] = set(cast(list[str], tokens))
        if actual_checks != REQUIRED_CHECKS[scenario_id]:
            fail(f"{scenario_id}: authority checks differ")
        for relative, tokens in actual_checks.items():
            path = repository / relative
            try:
                rendered = path.read_text(encoding="utf-8")
            except OSError as error:
                message = f"{scenario_id}: authority file is absent: {relative}"
                raise HandoffError(message) from error
            missing = sorted(token for token in tokens if token not in rendered)
            if missing:
                fail(f"{scenario_id}: authority tokens are absent from {relative}: {missing}")


def build_handoff(
    controls_merge_commit: str,
    controls_main_ci_run_id: str,
    repository: Path = ROOT,
) -> dict[str, Any]:
    """Build the exact operation, recovery, and escalation rehearsal receipt."""

    _validate_identifier(controls_merge_commit, r"[0-9a-f]{40}", "controls merge commit")
    _validate_identifier(controls_main_ci_run_id, r"[1-9][0-9]*", "controls main CI run ID")
    stage1, stage2 = _load_predecessors(repository)
    catalog = load_catalog(repository / CATALOG)
    validate_catalog(catalog, repository)
    rehearsals: list[dict[str, Any]] = []
    for scenario in cast(list[dict[str, Any]], catalog["scenarios"]):
        checks = cast(list[dict[str, Any]], scenario["authority_checks"])
        paths = [cast(str, check["path"]) for check in checks]
        rehearsals.append(
            {
                "authority_file_sha256": {
                    relative: sha256(repository / relative) for relative in sorted(paths)
                },
                "category": scenario["category"],
                "decision": scenario["decision"],
                "expected_evidence": scenario["expected_evidence"],
                "prohibited_actions": scenario["prohibited_actions"],
                "result": "PASS",
                "scenario_id": scenario["scenario_id"],
            }
        )
    payload: dict[str, Any] = {
        "actual_billed_cost_claim": "UNCLAIMED",
        "authority_file_sha256": {
            authority_id: sha256(repository / path)
            for authority_id, path in AUTHORITY_FILES.items()
        },
        "aws_execution": False,
        "claim_boundaries": stage1["claim_boundaries"],
        "claim_level": "LOCAL_VERIFIED",
        "closed_gap_ids": CLOSED_GAPS,
        "controls_authority": {
            "main_ci_run_id": controls_main_ci_run_id,
            "merge_commit": controls_merge_commit,
        },
        "evidence_type": "part5-stage3-operational-handoff",
        "part": 5,
        "project": "AtlasRetail",
        "project_completion": {
            "all_part5_stages_complete": False,
            "project_complete": False,
            "remaining_work_required": True,
        },
        "rehearsals": rehearsals,
        "remaining_gap_ids": REMAINING_GAPS,
        "runtime_equivalence": stage1["runtime_equivalence"],
        "schema_sha256": sha256(repository / SCHEMA),
        "schema_version": "1.0",
        "stage": 3,
        "stage1_contract_sha256": stage1["contract_sha256"],
        "stage2_receipt_sha256": stage2["receipt_sha256"],
        "state": "OPERATIONAL_HANDOFF_VERIFIED",
    }
    return {**payload, "receipt_sha256": digest(payload)}


def validate_handoff(receipt: dict[str, Any], repository: Path = ROOT) -> None:
    """Fail closed on authority drift, missing rehearsal coverage, or claim inflation."""

    controls = receipt.get("controls_authority")
    if not isinstance(controls, dict):
        fail("controls authority is absent")
    merge_commit = controls.get("merge_commit")
    main_ci_run_id = controls.get("main_ci_run_id")
    if not isinstance(merge_commit, str) or not isinstance(main_ci_run_id, str):
        fail("controls authority identifiers are absent")
    expected = build_handoff(merge_commit, main_ci_run_id, repository)
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
    categories = [row["category"] for row in receipt["rehearsals"]]
    if categories.count("OPERATION") != 1:
        fail("operation rehearsal coverage differs")
    if categories.count("RECOVERY") != 2:
        fail("recovery rehearsal coverage differs")
    if categories.count("ESCALATION") != 1:
        fail("escalation rehearsal coverage differs")
    if receipt["closed_gap_ids"] != CLOSED_GAPS:
        fail("closed gap set differs")
    if receipt["remaining_gap_ids"] != REMAINING_GAPS:
        fail("remaining gap set differs")


def validate_publication_authority(receipt: dict[str, Any], repository: Path = ROOT) -> None:
    """Require the recorded controls merge in this Stage 3 evidence history."""

    validate_handoff(receipt, repository)
    merge_commit = receipt["controls_authority"]["merge_commit"]
    exists = subprocess.run(
        ["git", "cat-file", "-e", f"{merge_commit}^{{commit}}"],
        cwd=repository,
        check=False,
        capture_output=True,
    )
    if exists.returncode != 0:
        fail("controls merge commit is absent from repository history")
    if merge_commit == STAGE2_MERGE_COMMIT:
        fail("controls merge commit does not identify the Stage 3 controls merge")
    for ancestor, descendant, message in (
        (STAGE2_MERGE_COMMIT, merge_commit, "controls merge does not descend from Stage 2"),
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


def load_handoff(path: Path) -> dict[str, Any]:
    """Load one handoff receipt and reject non-object content."""

    return _load_object(path)


def write_handoff(path: Path, receipt: dict[str, Any]) -> None:
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
            receipt = build_handoff(
                args.controls_merge_commit,
                args.controls_main_ci_run_id,
                ROOT,
            )
            write_handoff(args.output, receipt)
        else:
            validate_publication_authority(load_handoff(args.receipt), ROOT)
    except (HandoffError, OSError, subprocess.SubprocessError, ValueError) as error:
        print(f"Part 5 Stage 3 operational handoff rejected: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
