"""Validate Part 5 Stage 5 project-completion controls without claiming completion."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn, cast

from release.part5.stage4.validate_controls import validate as validate_stage4

from .project_completion import (
    ALL_GAPS,
    COMPLETION_TAG,
    COMPLETION_VERSION,
    POLICY,
    REQUIRED_JOBS,
    SCHEMA,
    STAGE4_EVIDENCE_MERGE_COMMIT,
    ProjectCompletionError,
    build_readiness,
    load_object,
    load_policy,
    sha256,
)

ROOT = Path(__file__).resolve().parents[3]
CI = Path(".github/workflows/ci.yml")
MAKEFILE = Path("Makefile")
ADR = Path("docs/adr/0014-part5-project-completion.md")
COMPLETION_DOCUMENT = Path("docs/project-completion.md")
MODULE = Path("release/part5/stage5/project_completion.py")
VALIDATOR = Path("release/part5/stage5/validate_controls.py")
TESTS = Path("tests/test_part5_stage5_project_completion.py")
HISTORICAL_STAGE4_VALIDATOR = Path("release/part5/stage4/completion_candidate.py")
DOCUMENTATION = {
    Path("README.md"),
    Path("CHANGELOG.md"),
    Path("docs/verification.md"),
    Path("evidence/README.md"),
    ADR,
    COMPLETION_DOCUMENT,
}
EXPECTED_FILES = {
    "release/part5/stage5/__init__.py",
    MODULE.as_posix(),
    VALIDATOR.as_posix(),
    SCHEMA.as_posix(),
    POLICY.as_posix(),
    ADR.as_posix(),
    COMPLETION_DOCUMENT.as_posix(),
    TESTS.as_posix(),
    HISTORICAL_STAGE4_VALIDATOR.as_posix(),
}
FROZEN_ROOTS = ("aws", "contracts", "infra", "scripts", "src")
PRESERVED_AUTHORITIES = (
    "evidence/part5/stage1/completion-contract.json",
    "evidence/part5/stage2/completion-gap.json",
    "evidence/part5/stage3/operational-handoff.json",
    "evidence/part5/stage4/completion-candidate.json",
)


class ControlsError(ValueError):
    """Raised when Stage 5 completion controls are absent or weakened."""


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
        "aws_execution",
        "claim_boundaries",
        "claim_level",
        "closed_gap_ids",
        "completion_tag",
        "evidence_type",
        "final_source",
        "gate_results",
        "objective_results",
        "part",
        "predecessor_authority_sha256",
        "project",
        "project_completion",
        "receipt_sha256",
        "required_job_results",
        "runtime_equivalence",
        "schema_sha256",
        "schema_version",
        "stage",
        "stage_results",
        "state",
    }
    require(set(properties) == expected, "schema and implementation keys differ")
    for name in (
        "claim_boundaries",
        "completion_tag",
        "final_source",
        "project_completion",
        "runtime_equivalence",
    ):
        _require_strict_object(cast(dict[str, Any], properties[name]), name)
    final_source = cast(dict[str, Any], properties["final_source"])["properties"]
    _require_strict_object(cast(dict[str, Any], final_source["main_ci"]), "main_ci")
    for name in ("gate_results", "objective_results", "required_job_results", "stage_results"):
        _require_strict_object(cast(dict[str, Any], properties[name]["items"]), name)
    project = cast(dict[str, Any], properties["project_completion"])["properties"]
    require(project["project_complete"].get("const") is True, "schema does not require completion")
    require(
        project["all_part5_stages_complete"].get("const") is True,
        "schema does not require all Part 5 stages",
    )
    require(
        project["remaining_work_required"].get("const") is False,
        "schema permits remaining completion work",
    )
    require(properties["aws_execution"].get("const") is False, "schema may claim Stage 5 AWS")
    require(properties["state"].get("const") == "PROJECT_COMPLETION_VERIFIED", "state differs")
    require(properties["closed_gap_ids"].get("minItems") == 6, "gap cardinality differs")
    require(properties["closed_gap_ids"].get("maxItems") == 6, "gap cardinality differs")
    require(properties["gate_results"].get("minItems") == 12, "gate cardinality differs")
    require(properties["objective_results"].get("minItems") == 7, "objective cardinality differs")
    require(properties["stage_results"].get("minItems") == 5, "stage cardinality differs")
    require(properties["required_job_results"].get("minItems") == 4, "job cardinality differs")


def validate_policy(policy: dict[str, Any]) -> None:
    require(policy.get("schema_version") == "1.0", "policy schema version differs")
    require(policy.get("closed_gap_ids") == ALL_GAPS, "policy gap closure differs")
    require(policy.get("required_ci_jobs") == REQUIRED_JOBS, "policy required jobs differ")
    tag = policy.get("completion_tag")
    require(isinstance(tag, dict), "completion tag policy is absent")
    tag_value = cast(dict[str, Any], tag)
    require(tag_value.get("tag") == COMPLETION_TAG, "completion tag differs")
    require(
        tag_value.get("completion_version") == COMPLETION_VERSION,
        "completion version differs",
    )
    require(tag_value.get("tag_type") == "ANNOTATED", "completion tag is not annotated")
    require(tag_value.get("signature_claim") == "NOT_CLAIMED", "signature claim differs")
    require(len(policy.get("completion_gates", [])) == 12, "completion gate coverage differs")
    require(len(policy.get("original_objectives", [])) == 7, "objective coverage differs")
    require(len(policy.get("stage_states", [])) == 5, "Part 5 stage coverage differs")
    require(
        policy.get("claim_boundaries")
        == {
            "production": "NOT_CLAIMED",
            "settled_billing": "UNCLAIMED",
            "sustained_operation": "NOT_ESTABLISHED",
        },
        "claim boundaries differ",
    )


def _changed_paths(repository: Path, *paths: str) -> list[str]:
    completed = subprocess.run(
        ["git", "diff", "--name-only", STAGE4_EVIDENCE_MERGE_COMMIT, "--", *paths],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return sorted(line for line in completed.stdout.splitlines() if line)


def validate_layout(repository: Path) -> None:
    tracked = set(
        subprocess.run(
            ["git", "ls-files"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )
    require(tracked >= EXPECTED_FILES, "Stage 5 control file set is incomplete")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", STAGE4_EVIDENCE_MERGE_COMMIT, "HEAD"],
        cwd=repository,
        check=False,
        capture_output=True,
    )
    require(ancestor.returncode == 0, "Stage 5 does not descend from merged Stage 4 evidence")
    changed = _changed_paths(repository, *FROZEN_ROOTS)
    require(not changed, f"Stage 5 changed the frozen managed surface: {changed}")
    authorities = _changed_paths(repository, *PRESERVED_AUTHORITIES)
    require(not authorities, f"Stage 5 changed predecessor authorities: {authorities}")


def validate_ci(path: Path) -> None:
    rendered = path.read_text(encoding="utf-8")
    required = (
        "release/part5/stage5",
        "release.part5.stage5.validate_controls",
        "Reproduce deterministic Part 5 Stage 5 project-completion controls",
        "project-completion-readiness:",
        "needs: [correctness, glue-runtime-integration, terraform]",
        "release.part5.stage5.project_completion readiness",
        "part5-stage5-project-completion-readiness-${{ github.run_id }}",
        "run: python -m pytest",
        "terraform -chdir=infra/atlas validate",
        "test_glue_spark_iceberg.py",
    )
    missing = [token for token in required if token not in rendered]
    require(not missing, f"CI is missing Stage 5 controls: {missing}")


def validate_makefile(path: Path) -> None:
    rendered = path.read_text(encoding="utf-8")
    required = (
        "release/part5/stage5",
        "python -m release.part5.stage5.validate_controls",
        "python -m release.part5.stage4.validate_controls",
    )
    missing = [token for token in required if token not in rendered]
    require(not missing, f"Makefile is missing Stage 5 controls: {missing}")


def validate_documentation(repository: Path) -> None:
    content = "\n".join(
        (repository / path).read_text(encoding="utf-8") for path in sorted(DOCUMENTATION)
    )
    required = (
        "Part 5 Stage 5",
        "FINAL_ATTESTATION_READY",
        "PROJECT_COMPLETION_VERIFIED",
        "P5-GAP-001",
        "P5-GAP-002",
        "v0.2.0",
        "annotated tag",
        "final `main` CI",
        "actual billed cost remains `UNCLAIMED`",
        "no AWS operation",
        "project completion remains false",
    )
    missing = [token for token in required if token not in content]
    require(not missing, f"Stage 5 documentation is incomplete: {missing}")


def validate(repository: Path = ROOT) -> dict[str, Any]:
    validate_schema(repository / SCHEMA)
    policy = load_policy(repository)
    validate_policy(policy)
    validate_layout(repository)
    validate_ci(repository / CI)
    validate_makefile(repository / MAKEFILE)
    validate_documentation(repository)
    prior = validate_stage4(repository)
    require(prior["result"] == "PASS", "Stage 4 controls no longer pass")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    first = build_readiness(head, 1, 1, repository)
    second = build_readiness(head, 1, 1, repository)
    require(first == second, "Stage 5 readiness is not deterministic")
    require(first["project_complete"] is False, "readiness falsely claims completion")
    controlled = sorted(
        EXPECTED_FILES
        | {CI.as_posix(), MAKEFILE.as_posix()}
        | {path.as_posix() for path in DOCUMENTATION}
    )
    return {
        "actual_billed_cost_claim": "UNCLAIMED",
        "aws_execution": False,
        "claim_level": "LOCAL_VERIFIED",
        "completion_tag": COMPLETION_TAG,
        "errors": [],
        "file_sha256": {
            path: hashlib.sha256((repository / path).read_bytes()).hexdigest()
            for path in controlled
        },
        "part": 5,
        "project": "AtlasRetail",
        "project_complete": False,
        "publication_boundary": "FINAL_REPOSITORY_MERGE_AND_MAIN_CI_REQUIRED",
        "remaining_gap_ids": ["P5-GAP-001", "P5-GAP-002"],
        "required_ci_jobs": REQUIRED_JOBS,
        "result": "PASS",
        "schema_sha256": sha256(repository / SCHEMA),
        "schema_version": "1.0",
        "stage": 5,
        "state": "PROJECT_COMPLETION_CONTROLS_READY",
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
        ProjectCompletionError,
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ) as error:
        print(f"Part 5 Stage 5 controls rejected: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
