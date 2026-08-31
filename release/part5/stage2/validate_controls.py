"""Validate repository-only Part 5 Stage 2 traceability controls."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn, cast

from release.part5.stage1.validate_controls import validate as validate_stage1

from .evidence_traceability import (
    GAPS,
    SCHEMA,
    STAGE1_MERGE_COMMIT,
    TraceabilityError,
    build_traceability,
    sha256,
    validate_traceability,
)

ROOT = Path(__file__).resolve().parents[3]
CI = Path(".github/workflows/ci.yml")
MAKEFILE = Path("Makefile")
ADR = Path("docs/adr/0011-part5-evidence-traceability.md")
MODULE = Path("release/part5/stage2/evidence_traceability.py")
VALIDATOR = Path("release/part5/stage2/validate_controls.py")
TESTS = Path("tests/test_part5_stage2_traceability.py")
DOCUMENTATION = {
    Path("README.md"),
    Path("CHANGELOG.md"),
    Path("docs/verification.md"),
    Path("docs/runbook.md"),
    Path("evidence/README.md"),
    ADR,
}
EXPECTED_FILES = {
    "release/__init__.py",
    "release/part5/__init__.py",
    "release/part5/stage2/__init__.py",
    MODULE.as_posix(),
    VALIDATOR.as_posix(),
    SCHEMA.as_posix(),
    ADR.as_posix(),
    TESTS.as_posix(),
}
FROZEN_ROOTS = ("aws", "contracts", "infra", "scripts", "src")


class ControlsError(ValueError):
    """Raised when Stage 2 controls are absent or weakened."""


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


def validate_schema(path: Path) -> None:
    schema = load(path)
    properties_value = schema.get("properties")
    require(schema.get("type") == "object", "gap schema does not describe an object")
    require(schema.get("additionalProperties") is False, "gap schema permits unknown keys")
    require(isinstance(properties_value, dict), "gap schema properties are absent")
    properties = cast(dict[str, Any], properties_value)
    required = schema.get("required")
    require(isinstance(required, list), "gap schema required keys are absent")
    require(
        set(cast(list[object], required)) == set(properties), "schema does not require every key"
    )
    expected = {
        "actual_billed_cost_claim",
        "authority_file_sha256",
        "aws_execution",
        "claim_boundaries",
        "claim_level",
        "controls_authority",
        "evidence_type",
        "gaps",
        "gate_traceability",
        "objective_traceability",
        "part",
        "project",
        "project_completion",
        "receipt_sha256",
        "schema_sha256",
        "schema_version",
        "stage",
        "stage1_contract_sha256",
        "state",
    }
    require(set(properties) == expected, "schema and implementation keys differ")
    for name in (
        "authority_file_sha256",
        "claim_boundaries",
        "controls_authority",
        "project_completion",
    ):
        nested = cast(dict[str, Any], properties[name])
        require(nested.get("additionalProperties") is False, f"schema {name} is not strict")
        nested_properties = nested.get("properties")
        nested_required = nested.get("required")
        require(isinstance(nested_properties, dict), f"schema {name} properties are absent")
        require(isinstance(nested_required, list), f"schema {name} required keys are absent")
        require(
            set(cast(list[object], nested_required))
            == set(cast(dict[str, Any], nested_properties)),
            f"schema {name} does not require every key",
        )
    definitions_value = schema.get("$defs")
    require(isinstance(definitions_value, dict), "schema definitions are absent")
    definitions = cast(dict[str, Any], definitions_value)
    require(
        set(definitions) == {"gap", "gate_traceability", "objective_traceability"},
        "schema definitions differ",
    )
    for name, value in definitions.items():
        definition = cast(dict[str, Any], value)
        require(definition.get("additionalProperties") is False, f"schema {name} is not strict")
        definition_properties = definition.get("properties")
        definition_required = definition.get("required")
        require(isinstance(definition_properties, dict), f"schema {name} properties are absent")
        require(isinstance(definition_required, list), f"schema {name} required keys are absent")
        require(
            set(cast(list[object], definition_required))
            == set(cast(dict[str, Any], definition_properties)),
            f"schema {name} does not require every key",
        )
    require(properties["aws_execution"].get("const") is False, "schema may claim AWS execution")
    require(
        properties["actual_billed_cost_claim"].get("const") == "UNCLAIMED",
        "schema may claim settled billing",
    )
    require(properties["claim_level"].get("const") == "LOCAL_VERIFIED", "claim level differs")
    project_completion = properties["project_completion"]["properties"]
    require(
        project_completion["project_complete"].get("const") is False,
        "schema claims project completion",
    )
    require(
        project_completion["all_part5_stages_complete"].get("const") is False,
        "schema claims Part 5 completion",
    )
    require(
        properties["gaps"].get("minItems") == len(GAPS)
        and properties["gaps"].get("maxItems") == len(GAPS),
        "schema gap cardinality differs",
    )


def validate_layout(repository: Path) -> None:
    tracked = set(tracked_files(repository))
    require(tracked >= EXPECTED_FILES, "Stage 2 control file set is incomplete")
    stage1_ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", STAGE1_MERGE_COMMIT, "HEAD"],
        cwd=repository,
        check=False,
        capture_output=True,
    )
    require(stage1_ancestor.returncode == 0, "Stage 2 does not descend from merged Stage 1")
    completed = subprocess.run(
        ["git", "diff", "--name-only", STAGE1_MERGE_COMMIT, "--", *FROZEN_ROOTS],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    changed = sorted(line for line in completed.stdout.splitlines() if line)
    require(not changed, f"Stage 2 changed the frozen managed surface: {changed}")


def validate_ci(path: Path) -> None:
    rendered = path.read_text(encoding="utf-8")
    required = (
        "mypy src release/part4/stage8 release/part5/stage1 release/part5/stage2",
        "release.part5.stage2.validate_controls",
        "Reproduce deterministic Part 5 Stage 2 traceability controls",
        "part5-stage2-traceability-controls-${{ github.run_id }}",
        "evidence/part5/stage2/completion-gap.json",
        "run: python -m pytest",
    )
    missing = [token for token in required if token not in rendered]
    require(not missing, f"CI is missing Stage 2 controls: {missing}")


def validate_makefile(path: Path) -> None:
    rendered = path.read_text(encoding="utf-8")
    required = (
        "mypy src release/part4/stage8 release/part5/stage1 release/part5/stage2",
        "python -m release.part5.stage2.validate_controls",
        "python -m release.part5.stage1.validate_controls",
        "python scripts/verify_part4_stage7_runtime.py",
    )
    missing = [token for token in required if token not in rendered]
    require(not missing, f"Makefile is missing Stage 2 controls: {missing}")


def validate_documentation(repository: Path) -> None:
    content = "\n".join(
        (repository / path).read_text(encoding="utf-8") for path in sorted(DOCUMENTATION)
    )
    required = (
        "Part 5 Stage 2",
        "TRACEABILITY_CONTROLS_READY",
        "GAP_BASELINE_RECORDED",
        "PRESERVED_PASS",
        "CURRENT_PASS_RECHECK_REQUIRED",
        "project completion remains false",
        "actual billed cost remains `UNCLAIMED`",
        "controls merge",
        "successful `main` CI",
    )
    missing = [token for token in required if token not in content]
    require(not missing, f"Stage 2 documentation is incomplete: {missing}")


def validate_naming(repository: Path) -> None:
    branded_names = ("co" + "dex", "chat" + "gpt", "open" + "ai")
    patterns = [re.escape(value) for value in branded_names]
    patterns.extend(("a" + r"i(?:-| )assisted", "generated by " + "a" + "i"))
    prohibited = re.compile(rf"(?i)\b(?:{'|'.join(patterns)})\b")
    violations: list[str] = []
    for relative in tracked_files(repository):
        path = repository / relative
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if prohibited.search(text):
            violations.append(relative)
    require(not violations, f"project naming policy violation: {violations}")


def validate_model(repository: Path) -> dict[str, Any]:
    first = build_traceability("a" * 40, "1", repository)
    second = build_traceability("a" * 40, "1", repository)
    require(first == second, "Stage 2 traceability is not deterministic")
    validate_traceability(first, repository)
    objective_rows = first["objective_traceability"]
    gate_rows = first["gate_traceability"]
    gap_rows = first["gaps"]
    require(len(objective_rows) == 7, "Stage 2 objective coverage differs")
    require(len(gate_rows) == 12, "Stage 2 gate coverage differs")
    require(len(gap_rows) == 6, "Stage 2 gap coverage differs")
    require(
        sum(row["status"] == "PRESERVED_PASS" for row in gate_rows) == 6,
        "preserved gate count differs",
    )
    require(all(row["blocking"] for row in gap_rows), "a completion gap is not blocking")
    return first


def validate(repository: Path = ROOT) -> dict[str, Any]:
    validate_schema(repository / SCHEMA)
    validate_layout(repository)
    validate_ci(repository / CI)
    validate_makefile(repository / MAKEFILE)
    validate_documentation(repository)
    validate_naming(repository)
    prior = validate_stage1(repository)
    require(prior["result"] == "PASS", "Stage 1 controls no longer pass")
    model = validate_model(repository)
    controlled = sorted(
        EXPECTED_FILES
        | {CI.as_posix(), MAKEFILE.as_posix()}
        | {path.as_posix() for path in DOCUMENTATION}
    )
    return {
        "actual_billed_cost_claim": "UNCLAIMED",
        "authority_file_sha256": model["authority_file_sha256"],
        "aws_execution": False,
        "claim_level": "LOCAL_VERIFIED",
        "errors": [],
        "file_sha256": {
            path: hashlib.sha256((repository / path).read_bytes()).hexdigest()
            for path in controlled
        },
        "gap_count": len(model["gaps"]),
        "gate_count": len(model["gate_traceability"]),
        "objective_count": len(model["objective_traceability"]),
        "part": 5,
        "project": "AtlasRetail",
        "project_complete": False,
        "publication_boundary": "CONTROLS_MERGE_AND_MAIN_CI_REQUIRED",
        "result": "PASS",
        "schema_sha256": sha256(repository / SCHEMA),
        "schema_version": "1.0",
        "stage": 2,
        "stage1_contract_sha256": prior["contract_sha256"],
        "state": "TRACEABILITY_CONTROLS_READY",
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
        OSError,
        TraceabilityError,
        ValueError,
        subprocess.SubprocessError,
    ) as error:
        print(f"Part 5 Stage 2 controls rejected: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
