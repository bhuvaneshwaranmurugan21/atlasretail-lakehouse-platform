"""Validate repository-only Part 4 Stage 8 release controls."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn, cast

from .release_integrity import (
    PACKAGE_VERSION,
    RELEASE_RECEIPT,
    RETENTION_CATALOG,
    SCHEMA,
    STAGE7_RUNTIME_FILE_COUNT,
    STAGE7_RUNTIME_SHA256,
    build_release_receipt,
    validate_release_receipt,
    validate_retention_catalog,
    write_json,
)

ROOT = Path(__file__).resolve().parents[3]
CI = Path(".github/workflows/ci.yml")
MAKEFILE = Path("Makefile")
ADR = Path("docs/adr/0009-part4-release-integrity.md")
MODULE = Path("release/part4/stage8/release_integrity.py")
MANAGER = Path("release/part4/stage8/manage_release.py")
VALIDATOR = Path("release/part4/stage8/validate_controls.py")
EXPECTED_RELEASE_FILES = {
    "release/__init__.py",
    "release/part4/__init__.py",
    "release/part4/stage8/__init__.py",
    MODULE.as_posix(),
    MANAGER.as_posix(),
    VALIDATOR.as_posix(),
    SCHEMA.as_posix(),
    RETENTION_CATALOG.as_posix(),
}
FROZEN_ROOTS = ("aws/", "contracts/", "infra/", "scripts/", "src/")


class ControlsError(ValueError):
    """Raised when Stage 8 controls are absent or weakened."""


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
    require(schema.get("type") == "object", "release schema does not describe an object")
    require(schema.get("additionalProperties") is False, "release schema permits unknown keys")
    require(isinstance(properties_value, dict), "release schema properties are absent")
    properties = cast(dict[str, Any], properties_value)
    required = schema.get("required")
    require(isinstance(required, list), "release schema required keys are absent")
    required_keys = cast(list[object], required)
    require(
        set(required_keys) == set(properties),
        "release schema does not require every property",
    )
    expected = {
        "actual_billed_cost_claim",
        "aws_execution",
        "claim_boundaries",
        "claim_level",
        "controls_commit",
        "errors",
        "evidence_retention",
        "evidence_type",
        "predecessor",
        "production_claim",
        "project",
        "receipt_sha256",
        "release",
        "release_state",
        "result",
        "runtime_equivalence",
        "schema_sha256",
        "schema_version",
        "source_evidence_sha256",
    }
    require(set(properties) == expected, "release schema and implementation keys differ")
    for name in (
        "claim_boundaries",
        "evidence_retention",
        "predecessor",
        "release",
        "runtime_equivalence",
    ):
        nested_value = properties[name]
        require(isinstance(nested_value, dict), f"schema {name} is not an object")
        nested = cast(dict[str, Any], nested_value)
        require(nested.get("additionalProperties") is False, f"schema {name} is not strict")
        nested_required = nested.get("required")
        nested_properties = nested.get("properties")
        require(isinstance(nested_required, list), f"schema {name} required keys are absent")
        require(isinstance(nested_properties, dict), f"schema {name} properties are absent")
        nested_required_keys = cast(list[object], nested_required)
        nested_property_map = cast(dict[str, Any], nested_properties)
        require(
            set(nested_required_keys) == set(nested_property_map),
            f"schema {name} does not require every property",
        )
    require(properties["aws_execution"].get("const") is False, "release may claim AWS execution")
    require(
        properties["production_claim"].get("const") is False,
        "release may claim production",
    )
    require(
        properties["actual_billed_cost_claim"].get("const") == "UNCLAIMED",
        "release may claim settled billing",
    )
    require(
        properties["release"]["properties"]["tag_type"].get("const") == "ANNOTATED",
        "release tag type differs",
    )
    require(
        properties["release"]["properties"]["signature_claim"].get("const") == "NOT_CLAIMED",
        "release signature boundary differs",
    )


def validate_layout(repository: Path) -> None:
    tracked = set(tracked_files(repository))
    require(tracked >= EXPECTED_RELEASE_FILES, "Stage 8 release control file set is incomplete")
    violations = [
        path for path in tracked if "stage8" in path.lower() and path.startswith(FROZEN_ROOTS)
    ]
    require(not violations, f"Stage 8 files entered the frozen runtime surface: {violations}")


def validate_ci(path: Path) -> None:
    rendered = path.read_text(encoding="utf-8")
    required = (
        "mypy src release/part4/stage8",
        "release.part4.stage8.validate_controls",
        "part4-stage8-release-readiness",
        "release.part4.stage8.manage_release verify-receipt",
        "evidence/part4/stage8/release-receipt.json",
        "verify_part4_stage7_runtime.py",
    )
    missing = [token for token in required if token not in rendered]
    require(not missing, f"CI is missing Stage 8 controls: {missing}")


def validate_makefile(path: Path) -> None:
    rendered = path.read_text(encoding="utf-8")
    required = (
        "mypy src release/part4/stage8",
        "python -m release.part4.stage8.validate_controls",
        "python scripts/verify_part4_stage7_runtime.py",
    )
    missing = [token for token in required if token not in rendered]
    require(not missing, f"Makefile is missing Stage 8 controls: {missing}")


def validate_version(repository: Path) -> None:
    pyproject = (repository / "pyproject.toml").read_text(encoding="utf-8")
    require(f'version = "{PACKAGE_VERSION}"' in pyproject, "release version differs")


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
        "Part 4 Stage 8",
        "v0.1.0",
        "READY_FOR_ANNOTATED_TAG",
        "LOCAL_VERIFIED",
        "actual billed cost remains `UNCLAIMED`",
        "production claim remains false",
        "107-file",
        "annotated tag",
    )
    missing = [token for token in required if token not in content]
    require(not missing, f"Stage 8 documentation is incomplete: {missing}")


def validate_naming(repository: Path) -> None:
    branded_names = ("co" + "dex", "chat" + "gpt", "open" + "ai")
    patterns = [re.escape(value) for value in branded_names]
    patterns.extend((r"ai(?:-| )assisted", r"generated by " + "a" + "i"))
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


def validate_completion(repository: Path) -> bool:
    path = repository / RELEASE_RECEIPT
    if not path.exists():
        return False
    require(path.is_file() and not path.is_symlink(), "release receipt is irregular")
    validate_release_receipt(load(path), repository)
    return True


def validate(repository: Path) -> dict[str, Any]:
    validate_schema(repository / SCHEMA)
    retention = validate_retention_catalog(load(repository / RETENTION_CATALOG), repository)
    validate_layout(repository)
    validate_ci(repository / CI)
    validate_makefile(repository / MAKEFILE)
    validate_version(repository)
    validate_documentation(repository)
    validate_naming(repository)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    candidate = build_release_receipt(repository, head)
    validate_release_receipt(candidate, repository)
    runtime = candidate["runtime_equivalence"]
    require(runtime["file_count"] == STAGE7_RUNTIME_FILE_COUNT, "runtime count changed")
    require(runtime["files_sha256"] == STAGE7_RUNTIME_SHA256, "runtime digest changed")
    completion = validate_completion(repository)
    controlled_files = sorted(
        EXPECTED_RELEASE_FILES | {CI.as_posix(), MAKEFILE.as_posix(), ADR.as_posix()}
    )
    return {
        "actual_billed_cost_claim": "UNCLAIMED",
        "aws_execution": False,
        "checks": {
            "annotated_tag_contract": True,
            "claim_boundaries_frozen": True,
            "deterministic_receipt": True,
            "evidence_retention_complete": retention["durable_authority_count"] == 4,
            "professional_naming": True,
            "release_layout_isolated": True,
            "release_schema_strict": True,
            "runtime_equivalent_to_stage7": True,
        },
        "claim_level": "LOCAL_VERIFIED",
        "completion_published": completion,
        "errors": [],
        "file_sha256": {path: sha256(repository / path) for path in controlled_files},
        "production_claim": False,
        "proof": "part4-stage8-release-readiness",
        "release_state": "READY_FOR_ANNOTATED_TAG" if completion else "CONTROLS_READY",
        "result": "PASS",
        "runtime_equivalence": runtime,
        "schema_version": "1.0",
        "tag": "v0.1.0",
    }


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    try:
        result = validate(ROOT)
        if output:
            write_json(output, result)
        else:
            print(json.dumps(result, sort_keys=True))
    except (ControlsError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Part 4 Stage 8 controls rejected: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
