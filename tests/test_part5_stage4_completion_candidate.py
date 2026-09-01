"""Adversarial checks for the Part 5 Stage 4 completion candidate."""

from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from atlasretail.canonical import digest
from release.part5.stage4 import completion_candidate as candidate
from release.part5.stage4.completion_candidate import (
    EVIDENCE,
    NEWLY_CLOSED_GAPS,
    POLICY,
    REMAINING_GAPS,
    SCHEMA,
    CompletionCandidateError,
    build_completion_candidate,
    build_naming_audit,
    load_object,
    load_policy,
    validate_action_pinning,
    validate_completion_candidate,
    validate_policy,
    validate_publication_authority,
    validate_sensitive_material,
)
from release.part5.stage4.validate_controls import ControlsError, validate, validate_schema

ROOT = Path(__file__).parents[1]
CONTROLS_MERGE_COMMIT = "a" * 40
CONTROLS_MAIN_CI_RUN_ID = "33470000000"


def resign(receipt: dict[str, Any]) -> None:
    payload = dict(receipt)
    payload.pop("receipt_sha256")
    receipt["receipt_sha256"] = digest(payload)


def build() -> dict[str, Any]:
    return build_completion_candidate(CONTROLS_MERGE_COMMIT, CONTROLS_MAIN_CI_RUN_ID, ROOT)


def test_candidate_is_deterministic_complete_and_fail_closed() -> None:
    first = build()
    second = build()
    assert first == second
    assert first["predecessor_closed_gap_ids"] == ["P5-GAP-003"]
    assert first["newly_closed_gap_ids"] == NEWLY_CLOSED_GAPS
    assert first["remaining_gap_ids"] == REMAINING_GAPS
    assert len(first["quality_audit"]["checks"]) == 16
    assert len(first["defect_audit"]["domain_results"]) == 12
    assert first["defect_audit"]["unresolved_critical_count"] == 0
    assert first["defect_audit"]["unresolved_high_count"] == 0
    validate_completion_candidate(first, ROOT)


def test_gap_partition_covers_every_stage2_gap_exactly_once() -> None:
    receipt = build()
    partitions = (
        set(receipt["predecessor_closed_gap_ids"]),
        set(receipt["newly_closed_gap_ids"]),
        set(receipt["remaining_gap_ids"]),
    )
    assert all(
        left.isdisjoint(right)
        for index, left in enumerate(partitions)
        for right in partitions[index + 1 :]
    )
    assert set().union(*partitions) == {f"P5-GAP-{number:03d}" for number in range(1, 7)}
    assert receipt["project_completion"]["project_complete"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("aws_execution", True),
        ("newly_closed_gap_ids", ["P5-GAP-001"]),
        ("remaining_gap_ids", []),
    ),
)
def test_candidate_rejects_claim_or_gap_inflation_when_resigned(field: str, value: object) -> None:
    receipt = deepcopy(build())
    receipt[field] = value
    resign(receipt)
    with pytest.raises(CompletionCandidateError, match="values differ"):
        validate_completion_candidate(receipt, ROOT)


def test_candidate_rejects_project_completion_inflation_when_resigned() -> None:
    receipt = deepcopy(build())
    receipt["project_completion"]["project_complete"] = True
    receipt["project_completion"]["remaining_work_required"] = False
    resign(receipt)
    with pytest.raises(CompletionCandidateError, match="values differ"):
        validate_completion_candidate(receipt, ROOT)


def test_candidate_rejects_unresolved_high_finding_when_resigned() -> None:
    receipt = deepcopy(build())
    receipt["defect_audit"]["unresolved_high_count"] = 1
    resign(receipt)
    with pytest.raises(CompletionCandidateError, match="values differ"):
        validate_completion_candidate(receipt, ROOT)


def test_candidate_rejects_removed_audit_domain_when_resigned() -> None:
    receipt = deepcopy(build())
    receipt["defect_audit"]["domain_results"].pop()
    resign(receipt)
    with pytest.raises(CompletionCandidateError, match="values differ"):
        validate_completion_candidate(receipt, ROOT)


def test_candidate_rejects_digest_mutation() -> None:
    receipt = build()
    receipt["receipt_sha256"] = "0" * 64
    with pytest.raises(CompletionCandidateError, match="digest differs"):
        validate_completion_candidate(receipt, ROOT)


def test_candidate_rejects_unknown_receipt_key() -> None:
    receipt = build()
    receipt["unexpected"] = True
    resign(receipt)
    with pytest.raises(CompletionCandidateError, match="keys differ"):
        validate_completion_candidate(receipt, ROOT)


@pytest.mark.parametrize(
    ("commit", "run_id", "message"),
    (
        ("A" * 40, CONTROLS_MAIN_CI_RUN_ID, "controls merge commit is invalid"),
        (CONTROLS_MERGE_COMMIT, "0", "controls main CI run ID is invalid"),
    ),
)
def test_candidate_rejects_invalid_publication_identifiers(
    commit: str, run_id: str, message: str
) -> None:
    with pytest.raises(CompletionCandidateError, match=message):
        build_completion_candidate(commit, run_id, ROOT)


def test_publication_authority_requires_real_stage4_commit() -> None:
    with pytest.raises(CompletionCandidateError, match="absent from repository history"):
        validate_publication_authority(build(), ROOT)


def test_policy_rejects_missing_defect_domain() -> None:
    policy = deepcopy(load_policy(ROOT / POLICY))
    policy["audit_domains"].pop()
    with pytest.raises(CompletionCandidateError, match="domain coverage"):
        validate_policy(policy)


def test_policy_rejects_critical_accepted_limitation() -> None:
    policy = deepcopy(load_policy(ROOT / POLICY))
    policy["accepted_limitations"][0]["severity"] = "CRITICAL"
    with pytest.raises(CompletionCandidateError, match="cannot be an accepted limitation"):
        validate_policy(policy)


def _initialize_repository(path: Path, relative: str, content: str) -> str:
    subprocess.run(["git", "init", "--quiet"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Stage 4 Test"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "stage4-test@example.invalid"], cwd=path, check=True
    )
    baseline = path / "README.md"
    baseline.write_text("Test repository\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "Initialize repository"], cwd=path, check=True
    )
    baseline.write_text("Test repository\nNaming policy boundary\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "Establish naming policy"], cwd=path, check=True
    )
    policy_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    target = path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "Create test fixture"], cwd=path, check=True)
    return policy_commit


@pytest.mark.parametrize("location", ["path", "content"])
def test_naming_audit_rejects_tracked_violations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, location: str
) -> None:
    prohibited = "co" + "dex"
    relative = f"docs/{prohibited}.md" if location == "path" else "docs/ordinary.md"
    content = prohibited if location == "content" else "ordinary content"
    commit = _initialize_repository(tmp_path, relative, content)
    monkeypatch.setattr(candidate, "NAMING_POLICY_COMMIT", commit)
    with pytest.raises(CompletionCandidateError, match="professional naming violations"):
        build_naming_audit(tmp_path)


def test_action_pinning_rejects_mutable_reference(tmp_path: Path) -> None:
    workflow = tmp_path / ".github/workflows/ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "jobs:\n  check:\n    steps:\n      - uses: actions/checkout@v4\n",
        encoding="utf-8",
    )
    with pytest.raises(CompletionCandidateError, match="not commit pinned"):
        validate_action_pinning(tmp_path)


def test_sensitive_material_scan_rejects_tracked_credential(tmp_path: Path) -> None:
    credential = "A" + "KIA" + "ABCDEFGHIJKLMNOP"
    _initialize_repository(tmp_path, "config/example.txt", credential)
    with pytest.raises(CompletionCandidateError, match="sensitive material detected"):
        validate_sensitive_material(tmp_path)


def test_candidate_schema_cannot_permit_unknown_properties(tmp_path: Path) -> None:
    schema = json.loads((ROOT / SCHEMA).read_text(encoding="utf-8"))
    schema["additionalProperties"] = True
    path = tmp_path / "completion-candidate.schema.json"
    path.write_text(json.dumps(schema), encoding="utf-8")
    with pytest.raises(ControlsError, match="permits unknown keys"):
        validate_schema(path)


def test_stage4_controls_preserve_non_completion() -> None:
    first = validate(ROOT)
    second = validate(ROOT)
    assert first == second
    assert first["result"] == "PASS"
    assert first["state"] == "COMPLETION_CANDIDATE_CONTROLS_READY"
    assert first["project_complete"] is False
    assert first["aws_execution"] is False
    assert first["newly_closed_gap_ids"] == NEWLY_CLOSED_GAPS
    assert first["remaining_gap_ids"] == REMAINING_GAPS
    assert first["unresolved_critical_count"] == 0
    assert first["unresolved_high_count"] == 0


def test_committed_receipt_is_verified_when_present() -> None:
    path = ROOT / EVIDENCE
    if path.is_file():
        validate_publication_authority(load_object(path), ROOT)
