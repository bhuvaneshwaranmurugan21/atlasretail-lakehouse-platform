"""Validate repository-only Part 5 Stage 4 completion-candidate controls."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn, cast

from release.part5.stage3.validate_controls import validate as validate_stage3

from .completion_candidate import (
    EVIDENCE,
    EXPECTED_CHECK_IDS,
    EXPECTED_DOMAIN_IDS,
    NEWLY_CLOSED_GAPS,
    POLICY,
    PREDECESSOR_CLOSED_GAPS,
    REMAINING_GAPS,
    SCHEMA,
    STAGE3_EVIDENCE_MERGE_COMMIT,
    CompletionCandidateError,
    build_completion_candidate,
    load_object,
    load_policy,
    sha256,
    tracked_files,
    validate_completion_candidate,
    validate_policy,
    validate_publication_authority,
)

ROOT = Path(__file__).resolve().parents[3]
CI = Path(".github/workflows/ci.yml")
MAKEFILE = Path("Makefile")
ADR = Path("docs/adr/0013-part5-completion-candidate.md")
QUALITY_DOCUMENT = Path("docs/repository-quality.md")
MODULE = Path("release/part5/stage4/completion_candidate.py")
VALIDATOR = Path("release/part5/stage4/validate_controls.py")
TESTS = Path("tests/test_part5_stage4_completion_candidate.py")
DOCUMENTATION = {
    Path("README.md"),
    Path("CHANGELOG.md"),
    Path("docs/verification.md"),
    Path("evidence/README.md"),
    ADR,
    QUALITY_DOCUMENT,
}
EXPECTED_FILES = {
    "release/__init__.py",
    "release/part5/__init__.py",
    "release/part5/stage4/__init__.py",
    MODULE.as_posix(),
    VALIDATOR.as_posix(),
    SCHEMA.as_posix(),
    POLICY.as_posix(),
    ADR.as_posix(),
    QUALITY_DOCUMENT.as_posix(),
    TESTS.as_posix(),
}
FROZEN_ROOTS = ("aws", "contracts", "infra", "scripts", "src")
PRESERVED_STAGE3_AUTHORITIES = (
    "docs/runbook.md",
    "release/part5/stage3/handoff-scenarios.json",
    "evidence/part5/stage3/operational-handoff.json",
)


class ControlsError(ValueError):
    """Raised when Stage 4 controls are absent or weakened."""


def fail(message: str) -> NoReturn:
    raise ControlsError(message)


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def _require_strict_object(value: dict[str, Any], name: str) -> None:
    require(value.get("type") == "object", f"schema {name} does not describe an object")
    require(value.get("additionalProperties") is False, f"schema {name} permits unknown keys")
    properties = value.get("properties")
    required = value.get("required")
    require(isinstance(properties, dict), f"schema {name} properties are absent")
    require(isinstance(required, list), f"schema {name} required keys are absent")
    require(
        set(cast(list[object], required)) == set(cast(dict[str, Any], properties)),
        f"schema {name} does not require every key",
    )


def validate_schema(path: Path) -> None:
    schema = load_object(path)
    _require_strict_object(schema, "root")
    properties = cast(dict[str, Any], schema["properties"])
    expected = {
        "actual_billed_cost_claim",
        "authority_file_sha256",
        "aws_execution",
        "claim_boundaries",
        "claim_level",
        "controls_authority",
        "defect_audit",
        "evidence_type",
        "naming_audit",
        "newly_closed_gap_ids",
        "part",
        "policy_sha256",
        "predecessor_closed_gap_ids",
        "project",
        "project_completion",
        "quality_audit",
        "receipt_sha256",
        "remaining_gap_ids",
        "runtime_equivalence",
        "schema_sha256",
        "schema_version",
        "stage",
        "stage1_contract_sha256",
        "stage2_receipt_sha256",
        "stage3_receipt_sha256",
        "state",
        "tracked_tree_sha256",
    }
    require(set(properties) == expected, "schema and implementation keys differ")
    definitions_value = schema.get("$defs")
    require(isinstance(definitions_value, dict), "schema definitions are absent")
    definitions = cast(dict[str, Any], definitions_value)
    require(
        set(definitions)
        == {
            "claim_boundaries",
            "controls_authority",
            "defect_audit",
            "domain_result",
            "finding",
            "naming_audit",
            "project_completion",
            "quality_audit",
            "quality_check",
            "runtime_equivalence",
        },
        "schema definitions differ",
    )
    for name, value in definitions.items():
        _require_strict_object(cast(dict[str, Any], value), name)
    require(properties["aws_execution"].get("const") is False, "schema may claim AWS execution")
    require(
        properties["actual_billed_cost_claim"].get("const") == "UNCLAIMED",
        "schema may claim settled billing",
    )
    require(properties["claim_level"].get("const") == "LOCAL_VERIFIED", "claim level differs")
    require(
        properties["state"].get("const") == "COMPLETION_CANDIDATE_VERIFIED",
        "schema state differs",
    )
    require(
        properties["predecessor_closed_gap_ids"].get("minItems") == len(PREDECESSOR_CLOSED_GAPS)
        and properties["predecessor_closed_gap_ids"].get("maxItems")
        == len(PREDECESSOR_CLOSED_GAPS),
        "schema predecessor-gap cardinality differs",
    )
    require(
        properties["newly_closed_gap_ids"].get("minItems") == len(NEWLY_CLOSED_GAPS)
        and properties["newly_closed_gap_ids"].get("maxItems") == len(NEWLY_CLOSED_GAPS),
        "schema newly-closed-gap cardinality differs",
    )
    require(
        properties["remaining_gap_ids"].get("minItems") == len(REMAINING_GAPS)
        and properties["remaining_gap_ids"].get("maxItems") == len(REMAINING_GAPS),
        "schema remaining-gap cardinality differs",
    )
    defect = cast(dict[str, Any], definitions["defect_audit"])["properties"]
    require(defect["unresolved_critical_count"].get("const") == 0, "critical defects allowed")
    require(defect["unresolved_high_count"].get("const") == 0, "high defects allowed")
    project = cast(dict[str, Any], definitions["project_completion"])["properties"]
    require(project["project_complete"].get("const") is False, "schema claims completion")
    require(
        project["all_part5_stages_complete"].get("const") is False,
        "schema claims all Part 5 stages complete",
    )


def _changed_paths(repository: Path, *paths: str) -> list[str]:
    completed = subprocess.run(
        ["git", "diff", "--name-only", STAGE3_EVIDENCE_MERGE_COMMIT, "--", *paths],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return sorted(line for line in completed.stdout.splitlines() if line)


def validate_layout(repository: Path) -> None:
    tracked = set(tracked_files(repository))
    require(tracked >= EXPECTED_FILES, "Stage 4 control file set is incomplete")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", STAGE3_EVIDENCE_MERGE_COMMIT, "HEAD"],
        cwd=repository,
        check=False,
        capture_output=True,
    )
    require(ancestor.returncode == 0, "Stage 4 does not descend from merged Stage 3 evidence")
    changed = _changed_paths(repository, *FROZEN_ROOTS)
    require(not changed, f"Stage 4 changed the frozen managed surface: {changed}")
    changed_authorities = _changed_paths(repository, *PRESERVED_STAGE3_AUTHORITIES)
    require(not changed_authorities, f"Stage 4 changed Stage 3 authorities: {changed_authorities}")


def validate_ci(path: Path) -> None:
    rendered = path.read_text(encoding="utf-8")
    required = (
        "release/part5/stage4",
        "release.part5.stage4.validate_controls",
        "Reproduce deterministic Part 5 Stage 4 completion-candidate controls",
        "part5-stage4-completion-candidate-controls-${{ github.run_id }}",
        "evidence/part5/stage4/completion-candidate.json",
        "run: python -m pytest",
        "terraform -chdir=infra/atlas validate",
        "test_glue_spark_iceberg.py",
    )
    missing = [token for token in required if token not in rendered]
    require(not missing, f"CI is missing Stage 4 controls: {missing}")


def validate_makefile(path: Path) -> None:
    rendered = path.read_text(encoding="utf-8")
    required = (
        "release/part5/stage4",
        "python -m release.part5.stage4.validate_controls",
        "python -m release.part5.stage3.validate_controls",
        "python scripts/verify_part4_stage7_runtime.py",
    )
    missing = [token for token in required if token not in rendered]
    require(not missing, f"Makefile is missing Stage 4 controls: {missing}")


def validate_documentation(repository: Path) -> None:
    content = "\n".join(
        (repository / path).read_text(encoding="utf-8") for path in sorted(DOCUMENTATION)
    )
    required = (
        "Part 5 Stage 4",
        "COMPLETION_CANDIDATE_CONTROLS_READY",
        "COMPLETION_CANDIDATE_VERIFIED",
        "P5-GAP-004",
        "P5-GAP-005",
        "P5-GAP-006",
        "P5-GAP-001",
        "P5-GAP-002",
        "project completion remains false",
        "actual billed cost remains `UNCLAIMED`",
        "no AWS operation",
    )
    missing = [token for token in required if token not in content]
    require(not missing, f"Stage 4 documentation is incomplete: {missing}")


def validate_model(repository: Path) -> dict[str, Any]:
    policy = load_policy(repository / POLICY)
    validate_policy(policy)
    first = build_completion_candidate("a" * 40, "1", repository)
    second = build_completion_candidate("a" * 40, "1", repository)
    require(first == second, "Stage 4 completion candidate is not deterministic")
    validate_completion_candidate(first, repository)
    require(
        len(first["quality_audit"]["checks"]) == len(EXPECTED_CHECK_IDS),
        "Stage 4 quality-check coverage differs",
    )
    require(
        len(first["defect_audit"]["domain_results"]) == len(EXPECTED_DOMAIN_IDS),
        "Stage 4 defect-domain coverage differs",
    )
    require(first["newly_closed_gap_ids"] == NEWLY_CLOSED_GAPS, "newly closed gaps differ")
    require(first["remaining_gap_ids"] == REMAINING_GAPS, "remaining gaps differ")
    require(first["project_completion"]["project_complete"] is False, "completion inflated")
    require(first["aws_execution"] is False, "Stage 4 claims AWS execution")
    return first


def validate(repository: Path = ROOT) -> dict[str, Any]:
    validate_schema(repository / SCHEMA)
    validate_layout(repository)
    validate_ci(repository / CI)
    validate_makefile(repository / MAKEFILE)
    validate_documentation(repository)
    prior = validate_stage3(repository)
    require(prior["result"] == "PASS", "Stage 3 controls no longer pass")
    model = validate_model(repository)
    if (repository / EVIDENCE).is_file():
        validate_publication_authority(load_object(repository / EVIDENCE), repository)
    controlled = sorted(
        EXPECTED_FILES
        | {CI.as_posix(), MAKEFILE.as_posix()}
        | {path.as_posix() for path in DOCUMENTATION}
    )
    return {
        "actual_billed_cost_claim": "UNCLAIMED",
        "aws_execution": False,
        "claim_level": "LOCAL_VERIFIED",
        "defect_domain_count": len(model["defect_audit"]["domain_results"]),
        "errors": [],
        "file_sha256": {
            path: hashlib.sha256((repository / path).read_bytes()).hexdigest()
            for path in controlled
        },
        "newly_closed_gap_ids": model["newly_closed_gap_ids"],
        "part": 5,
        "predecessor_closed_gap_ids": model["predecessor_closed_gap_ids"],
        "project": "AtlasRetail",
        "project_complete": False,
        "publication_boundary": "CONTROLS_MERGE_AND_MAIN_CI_REQUIRED",
        "quality_check_count": len(model["quality_audit"]["checks"]),
        "remaining_gap_ids": model["remaining_gap_ids"],
        "result": "PASS",
        "schema_sha256": sha256(repository / SCHEMA),
        "schema_version": "1.0",
        "stage": 4,
        "state": "COMPLETION_CANDIDATE_CONTROLS_READY",
        "unresolved_critical_count": model["defect_audit"]["unresolved_critical_count"],
        "unresolved_high_count": model["defect_audit"]["unresolved_high_count"],
    }


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    try:
        result = validate(ROOT)
        rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if output:
            output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
    except (
        CompletionCandidateError,
        ControlsError,
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ) as error:
        print(f"Part 5 Stage 4 controls rejected: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
