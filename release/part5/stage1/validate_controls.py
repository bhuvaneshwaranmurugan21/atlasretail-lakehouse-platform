"""Validate repository-only Part 5 Stage 1 completion-contract controls."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn, cast

from release.part4.stage8.validate_controls import validate as validate_part4_release

from .completion_contract import (
    CONTRACT,
    PART4_RELEASE_COMMIT,
    PART4_RUNTIME_SHA256,
    PART4_TAG_OBJECT,
    SCHEMA,
    CompletionContractError,
    load_contract,
    validate_contract,
)

ROOT = Path(__file__).resolve().parents[3]
CI = Path(".github/workflows/ci.yml")
MAKEFILE = Path("Makefile")
ADR = Path("docs/adr/0010-part5-completion-contract.md")
MODULE = Path("release/part5/stage1/completion_contract.py")
VALIDATOR = Path("release/part5/stage1/validate_controls.py")
TESTS = Path("tests/test_part5_stage1_contract.py")
EXPECTED_FILES = {
    "release/__init__.py",
    "release/part5/__init__.py",
    "release/part5/stage1/__init__.py",
    MODULE.as_posix(),
    VALIDATOR.as_posix(),
    SCHEMA.as_posix(),
    CONTRACT.as_posix(),
    ADR.as_posix(),
    TESTS.as_posix(),
}
FROZEN_ROOTS = ("aws", "contracts", "infra", "scripts", "src")


class ControlsError(ValueError):
    """Raised when Stage 1 controls are absent or weakened."""


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


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    require(schema.get("type") == "object", "completion schema does not describe an object")
    require(schema.get("additionalProperties") is False, "completion schema permits unknown keys")
    require(isinstance(properties_value, dict), "completion schema properties are absent")
    properties = cast(dict[str, Any], properties_value)
    required = schema.get("required")
    require(isinstance(required, list), "completion schema required keys are absent")
    require(
        set(cast(list[object], required)) == set(properties),
        "schema does not require every key",
    )
    expected = {
        "actual_billed_cost_claim",
        "aws_execution",
        "claim_boundaries",
        "claim_level",
        "completion_gates",
        "contract_sha256",
        "evidence_type",
        "original_objectives",
        "part",
        "predecessor",
        "project",
        "project_completion",
        "runtime_equivalence",
        "schema_sha256",
        "schema_version",
        "source_evidence_sha256",
        "stage",
        "state",
    }
    require(set(properties) == expected, "schema and implementation keys differ")
    for name in (
        "claim_boundaries",
        "predecessor",
        "project_completion",
        "runtime_equivalence",
    ):
        nested_value = properties[name]
        require(isinstance(nested_value, dict), f"schema {name} is not an object")
        nested = cast(dict[str, Any], nested_value)
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
    require(properties["aws_execution"].get("const") is False, "schema may claim AWS execution")
    require(
        properties["actual_billed_cost_claim"].get("const") == "UNCLAIMED",
        "schema may claim settled billing",
    )
    project_completion = properties["project_completion"]["properties"]
    require(
        project_completion["project_complete"].get("const") is False,
        "schema claims completion",
    )
    require(
        project_completion["part5_completion_equals_project_completion"].get("const") is True,
        "schema weakens the final completion definition",
    )


def validate_layout(repository: Path) -> None:
    tracked = set(tracked_files(repository))
    require(tracked >= EXPECTED_FILES, "Stage 1 control file set is incomplete")
    completed = subprocess.run(
        ["git", "diff", "--name-only", PART4_RELEASE_COMMIT, "--", *FROZEN_ROOTS],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    changed = sorted(line for line in completed.stdout.splitlines() if line)
    require(not changed, f"Stage 1 changed the frozen managed surface: {changed}")


def validate_tag(repository: Path) -> None:
    tag_type = subprocess.run(
        ["git", "cat-file", "-t", "v0.1.0"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tag_object = subprocess.run(
        ["git", "rev-parse", "v0.1.0"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tag_commit = subprocess.run(
        ["git", "rev-parse", "v0.1.0^{commit}"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    require(tag_type == "tag", "Part 4 release tag is not annotated")
    require(tag_object == PART4_TAG_OBJECT, "Part 4 tag object differs")
    require(tag_commit == PART4_RELEASE_COMMIT, "Part 4 tag target differs")


def validate_ci(path: Path) -> None:
    rendered = path.read_text(encoding="utf-8")
    required = (
        "mypy src release/part4/stage8 release/part5/stage1",
        "release.part5.stage1.validate_controls",
        "part5-stage1-completion-contract",
        "verify_part4_stage7_runtime.py",
        "run: python -m pytest",
    )
    missing = [token for token in required if token not in rendered]
    require(not missing, f"CI is missing Stage 1 controls: {missing}")


def validate_makefile(path: Path) -> None:
    rendered = path.read_text(encoding="utf-8")
    required = (
        "mypy src release/part4/stage8 release/part5/stage1",
        "python -m release.part5.stage1.validate_controls",
        "python scripts/verify_part4_stage7_runtime.py",
    )
    missing = [token for token in required if token not in rendered]
    require(not missing, f"Makefile is missing Stage 1 controls: {missing}")


def validate_documentation(repository: Path) -> None:
    content = "\n".join(
        (repository / path).read_text(encoding="utf-8")
        for path in (
            Path("README.md"),
            Path("CHANGELOG.md"),
            Path("docs/verification.md"),
            Path("docs/runbook.md"),
            Path("evidence/README.md"),
            ADR,
        )
    )
    required = (
        "Part 5 Stage 1",
        "CONTRACT_FROZEN",
        "Part 5 completion equals project completion",
        "project completion remains false",
        "actual billed cost remains `UNCLAIMED`",
        "107-file",
        "v0.1.0",
    )
    missing = [token for token in required if token not in content]
    require(not missing, f"Stage 1 documentation is incomplete: {missing}")


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


def validate(repository: Path = ROOT) -> dict[str, Any]:
    validate_schema(repository / SCHEMA)
    validate_layout(repository)
    validate_tag(repository)
    validate_ci(repository / CI)
    validate_makefile(repository / MAKEFILE)
    validate_documentation(repository)
    validate_naming(repository)
    prior = validate_part4_release(repository)
    require(prior["result"] == "PASS", "Part 4 release controls no longer pass")
    require(
        prior["runtime_equivalence"]["files_sha256"] == PART4_RUNTIME_SHA256,
        "Part 4 runtime digest differs",
    )
    contract = load_contract(repository / CONTRACT)
    validate_contract(contract, repository)
    controlled = sorted(EXPECTED_FILES | {CI.as_posix(), MAKEFILE.as_posix()})
    return {
        "actual_billed_cost_claim": "UNCLAIMED",
        "aws_execution": False,
        "claim_level": "LOCAL_VERIFIED",
        "contract_sha256": contract["contract_sha256"],
        "errors": [],
        "file_sha256": {path: sha256(repository / path) for path in controlled},
        "part": 5,
        "project": "AtlasRetail",
        "project_complete": False,
        "proof": "part5-stage1-completion-contract",
        "result": "PASS",
        "runtime_equivalence": prior["runtime_equivalence"],
        "schema_version": "1.0",
        "stage": 1,
        "state": "CONTRACT_FROZEN",
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
        CompletionContractError,
        ControlsError,
        OSError,
        ValueError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"Part 5 Stage 1 controls rejected: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
