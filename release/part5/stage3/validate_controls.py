"""Validate repository-only Part 5 Stage 3 operational-handoff controls."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn, cast

from release.part5.stage2.validate_controls import validate as validate_stage2

from .operational_handoff import (
    CATALOG,
    CLOSED_GAPS,
    EVIDENCE,
    REMAINING_GAPS,
    SCHEMA,
    STAGE2_MERGE_COMMIT,
    HandoffError,
    build_handoff,
    load_catalog,
    load_handoff,
    sha256,
    validate_catalog,
    validate_handoff,
    validate_publication_authority,
)

ROOT = Path(__file__).resolve().parents[3]
CI = Path(".github/workflows/ci.yml")
MAKEFILE = Path("Makefile")
ADR = Path("docs/adr/0012-part5-operational-handoff.md")
HANDOFF_DOCUMENT = Path("docs/operational-handoff.md")
MODULE = Path("release/part5/stage3/operational_handoff.py")
VALIDATOR = Path("release/part5/stage3/validate_controls.py")
TESTS = Path("tests/test_part5_stage3_operational_handoff.py")
DOCUMENTATION = {
    Path("README.md"),
    Path("CHANGELOG.md"),
    Path("docs/verification.md"),
    Path("docs/runbook.md"),
    Path("evidence/README.md"),
    ADR,
    HANDOFF_DOCUMENT,
}
EXPECTED_FILES = {
    "release/__init__.py",
    "release/part5/__init__.py",
    "release/part5/stage3/__init__.py",
    MODULE.as_posix(),
    VALIDATOR.as_posix(),
    SCHEMA.as_posix(),
    CATALOG.as_posix(),
    ADR.as_posix(),
    HANDOFF_DOCUMENT.as_posix(),
    TESTS.as_posix(),
}
FROZEN_ROOTS = ("aws", "contracts", "infra", "scripts", "src")


class ControlsError(ValueError):
    """Raised when Stage 3 controls are absent or weakened."""


def fail(message: str) -> NoReturn:
    raise ControlsError(message)


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def load(path: Path) -> dict[str, Any]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        fail(f"{path}: expected a JSON object")
    return value


def tracked_files(repository: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    return sorted(value.decode() for value in completed.stdout.split(b"\0") if value)


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
    schema = load(path)
    _require_strict_object(schema, "root")
    properties = cast(dict[str, Any], schema["properties"])
    expected = {
        "actual_billed_cost_claim",
        "authority_file_sha256",
        "aws_execution",
        "claim_boundaries",
        "claim_level",
        "closed_gap_ids",
        "controls_authority",
        "evidence_type",
        "part",
        "project",
        "project_completion",
        "receipt_sha256",
        "rehearsals",
        "remaining_gap_ids",
        "runtime_equivalence",
        "schema_sha256",
        "schema_version",
        "stage",
        "stage1_contract_sha256",
        "stage2_receipt_sha256",
        "state",
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
            "project_completion",
            "rehearsal",
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
    require(properties["state"].get("const") == "OPERATIONAL_HANDOFF_VERIFIED", "state differs")
    closed = properties["closed_gap_ids"]
    require(
        closed.get("minItems") == 1
        and closed.get("maxItems") == 1
        and closed["items"].get("const") == "P5-GAP-003",
        "schema closed-gap boundary differs",
    )
    remaining = properties["remaining_gap_ids"]
    require(
        remaining.get("minItems") == len(REMAINING_GAPS)
        and remaining.get("maxItems") == len(REMAINING_GAPS),
        "schema remaining-gap cardinality differs",
    )
    rehearsals = properties["rehearsals"]
    require(
        rehearsals.get("minItems") == 4 and rehearsals.get("maxItems") == 4,
        "schema rehearsal cardinality differs",
    )
    project = cast(dict[str, Any], definitions["project_completion"])["properties"]
    require(project["project_complete"].get("const") is False, "schema claims completion")
    require(
        project["all_part5_stages_complete"].get("const") is False,
        "schema claims Part 5 completion",
    )


def validate_layout(repository: Path) -> None:
    tracked = set(tracked_files(repository))
    require(tracked >= EXPECTED_FILES, "Stage 3 control file set is incomplete")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", STAGE2_MERGE_COMMIT, "HEAD"],
        cwd=repository,
        check=False,
        capture_output=True,
    )
    require(ancestor.returncode == 0, "Stage 3 does not descend from merged Stage 2")
    completed = subprocess.run(
        ["git", "diff", "--name-only", STAGE2_MERGE_COMMIT, "--", *FROZEN_ROOTS],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    changed = sorted(line for line in completed.stdout.splitlines() if line)
    require(not changed, f"Stage 3 changed the frozen managed surface: {changed}")


def validate_ci(path: Path) -> None:
    rendered = path.read_text(encoding="utf-8")
    required = (
        "release/part5/stage3",
        "release.part5.stage3.validate_controls",
        "Reproduce deterministic Part 5 Stage 3 operational-handoff controls",
        "part5-stage3-operational-handoff-controls-${{ github.run_id }}",
        "evidence/part5/stage3/operational-handoff.json",
        "run: python -m pytest",
    )
    missing = [token for token in required if token not in rendered]
    require(not missing, f"CI is missing Stage 3 controls: {missing}")


def validate_makefile(path: Path) -> None:
    rendered = path.read_text(encoding="utf-8")
    required = (
        "release/part5/stage3",
        "python -m release.part5.stage3.validate_controls",
        "python -m release.part5.stage2.validate_controls",
        "python scripts/verify_part4_stage7_runtime.py",
    )
    missing = [token for token in required if token not in rendered]
    require(not missing, f"Makefile is missing Stage 3 controls: {missing}")


def validate_documentation(repository: Path) -> None:
    content = "\n".join(
        (repository / path).read_text(encoding="utf-8") for path in sorted(DOCUMENTATION)
    )
    required = (
        "Part 5 Stage 3",
        "HANDOFF_CONTROLS_READY",
        "OPERATIONAL_HANDOFF_VERIFIED",
        "P5-GAP-003",
        "normal operation",
        "authority-bound recovery",
        "lease-only recovery",
        "stop and escalate",
        "project completion remains false",
        "actual billed cost remains `UNCLAIMED`",
        "no AWS operation",
    )
    missing = [token for token in required if token not in content]
    require(not missing, f"Stage 3 documentation is incomplete: {missing}")


def validate_model(repository: Path) -> dict[str, Any]:
    catalog = load_catalog(repository / CATALOG)
    validate_catalog(catalog, repository)
    first = build_handoff("a" * 40, "1", repository)
    second = build_handoff("a" * 40, "1", repository)
    require(first == second, "Stage 3 handoff is not deterministic")
    validate_handoff(first, repository)
    require(len(first["rehearsals"]) == 4, "Stage 3 rehearsal coverage differs")
    require(first["closed_gap_ids"] == CLOSED_GAPS, "Stage 3 closed gap set differs")
    require(first["remaining_gap_ids"] == REMAINING_GAPS, "Stage 3 remaining gaps differ")
    require(first["project_completion"]["project_complete"] is False, "project completion inflated")
    require(first["aws_execution"] is False, "Stage 3 claims AWS execution")
    return first


def validate(repository: Path = ROOT) -> dict[str, Any]:
    validate_schema(repository / SCHEMA)
    validate_layout(repository)
    validate_ci(repository / CI)
    validate_makefile(repository / MAKEFILE)
    validate_documentation(repository)
    prior = validate_stage2(repository)
    require(prior["result"] == "PASS", "Stage 2 controls no longer pass")
    model = validate_model(repository)
    if (repository / EVIDENCE).is_file():
        validate_publication_authority(load_handoff(repository / EVIDENCE), repository)
    controlled = sorted(
        EXPECTED_FILES
        | {CI.as_posix(), MAKEFILE.as_posix()}
        | {path.as_posix() for path in DOCUMENTATION}
    )
    return {
        "actual_billed_cost_claim": "UNCLAIMED",
        "aws_execution": False,
        "claim_level": "LOCAL_VERIFIED",
        "closed_gap_ids": model["closed_gap_ids"],
        "errors": [],
        "file_sha256": {
            path: hashlib.sha256((repository / path).read_bytes()).hexdigest()
            for path in controlled
        },
        "part": 5,
        "project": "AtlasRetail",
        "project_complete": False,
        "publication_boundary": "CONTROLS_MERGE_AND_MAIN_CI_REQUIRED",
        "rehearsal_count": len(model["rehearsals"]),
        "remaining_gap_ids": model["remaining_gap_ids"],
        "result": "PASS",
        "schema_sha256": sha256(repository / SCHEMA),
        "schema_version": "1.0",
        "stage": 3,
        "state": "HANDOFF_CONTROLS_READY",
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
        ControlsError,
        HandoffError,
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ) as error:
        print(f"Part 5 Stage 3 controls rejected: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
