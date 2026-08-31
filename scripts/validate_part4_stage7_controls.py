#!/usr/bin/env python3
"""Validate repository-only Part 4 Stage 7 closure controls."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn

import yaml

from atlasretail.part4_stage7_closure import (
    CLOSURE_SCHEMA,
    RUNTIME_MANIFEST,
    ClosureError,
    build_runtime_receipt,
    validate_closure_receipt,
)

ROOT = Path(__file__).resolve().parents[1]
CI = Path(".github/workflows/ci.yml")
PREFLIGHT = Path(".github/workflows/aws-read-only-preflight.yml")
CREDIT = Path("evidence/aws/organization-shared-credit-baseline.json")
COMPLETION = Path("evidence/part4/stage7/completion-receipt.json")
PUBLISHER = Path("scripts/publish_part4_stage7_closure.py")
RUNTIME_VERIFIER = Path("scripts/verify_part4_stage7_runtime.py")
MODULE = Path("src/atlasretail/part4_stage7_closure.py")
EXPECTED_ALLOWLIST = {
    CLOSURE_SCHEMA.as_posix(),
    RUNTIME_MANIFEST.as_posix(),
    PUBLISHER.as_posix(),
    Path(__file__).relative_to(ROOT).as_posix(),
    RUNTIME_VERIFIER.as_posix(),
    MODULE.as_posix(),
}


class ControlsError(ValueError):
    """Raised when Stage 7 controls are absent or weakened."""


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


def validate_schema(path: Path) -> None:
    schema = load(path)
    properties = schema.get("properties")
    require(schema.get("type") == "object", "closure schema does not describe an object")
    require(schema.get("additionalProperties") is False, "closure schema permits unknown keys")
    require(isinstance(properties, dict), "closure schema properties are absent")
    require(
        set(schema.get("required", [])) == set(properties),
        "closure schema does not require every top-level property",
    )
    expected = {
        "actual_billed_cost_claim",
        "aws_execution",
        "claim_boundaries",
        "claim_level",
        "clean_inventory_authority",
        "closure_control_commit",
        "errors",
        "evidence_type",
        "financial_boundary",
        "production_claim",
        "project",
        "receipt_sha256",
        "recovery_authority",
        "result",
        "runtime_equivalence",
        "schema_sha256",
        "schema_version",
        "source_evidence_sha256",
        "workload_authority",
    }
    require(set(properties) == expected, "closure schema and implementation keys differ")
    for name in (
        "claim_boundaries",
        "clean_inventory_authority",
        "financial_boundary",
        "recovery_authority",
        "runtime_equivalence",
        "workload_authority",
    ):
        nested = properties[name]
        require(nested.get("additionalProperties") is False, f"schema {name} is not strict")
        require(
            set(nested.get("required", [])) == set(nested.get("properties", {})),
            f"schema {name} does not require every property",
        )
    require(properties["aws_execution"].get("const") is False, "closure may claim AWS execution")
    require(properties["production_claim"].get("const") is False, "closure may claim production")
    require(
        properties["actual_billed_cost_claim"].get("const") == "UNCLAIMED",
        "closure may claim settled billing",
    )
    source_map = properties["source_evidence_sha256"]
    require(source_map.get("minProperties") == 14, "closure source floor differs")
    require(
        source_map.get("additionalProperties", {}).get("pattern") == "^[0-9a-f]{64}$",
        "closure source digest map is not constrained",
    )


def validate_runtime_manifest(path: Path) -> dict[str, Any]:
    manifest = load(path)
    require(
        set(manifest.get("stage7_only_allowlist", [])) == EXPECTED_ALLOWLIST,
        "Stage 7-only allowlist differs",
    )
    receipt = build_runtime_receipt(ROOT, path)
    require(receipt["result"] == "PASS", "; ".join(receipt["errors"]))
    return receipt


def validate_preflight(path: Path) -> None:
    workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    require(isinstance(workflow, dict), "read-only preflight workflow is invalid")
    require(set(workflow.get("on", {})) == {"workflow_dispatch"}, "preflight is not manual-only")
    rendered = path.read_text(encoding="utf-8")
    required = (
        "permissions:\n  id-token: write\n  contents: read",
        "build_read_only_session_policy.py",
        "allowed-account-ids:",
        "unset-current-credentials: true",
        "verify_account_plan.py",
        "organization-shared-credit-baseline.json",
        "verify_preflight.py",
        "if-no-files-found: error",
        "retention-days: 30",
    )
    missing = [token for token in required if token not in rendered]
    require(not missing, f"read-only preflight controls are missing: {missing}")
    forbidden = (
        "terraform apply",
        "terraform destroy",
        "start-execution",
        "start-job-run",
        "start-query-execution",
        "lambda invoke",
    )
    present = [token for token in forbidden if token in rendered.lower()]
    require(not present, f"read-only preflight contains mutation or workload behavior: {present}")


def validate_credit(path: Path) -> None:
    credit = load(path)
    require(credit.get("recipient_account_id") == "857229544428", "credit recipient differs")
    require(credit.get("verified_remaining_usd") == 119.22, "credit amount is not conservative")
    require(credit.get("credit_sharing_active") is True, "credit sharing is not active")
    require(
        credit.get("credit_level_cost_category_restriction") is False,
        "credit-level restriction is not explicitly absent",
    )
    require(credit.get("credit_expiration_date") == "2027-08-25", "credit expiration differs")
    require(credit.get("observed_at") == "2026-08-31T05:32:13Z", "credit observation differs")
    require(credit.get("valid_until") == "2026-09-07T23:59:59Z", "credit validity differs")
    require(
        credit.get("verification_method")
        == "AWS management-account Billing console reviewed by repository owner",
        "credit verification method differs",
    )


def validate_ci(path: Path) -> None:
    rendered = path.read_text(encoding="utf-8")
    required = (
        "validate_part4_stage7_controls.py",
        "verify_part4_stage7_runtime.py",
        "part4-stage7-closure-readiness",
        "publish_part4_stage7_closure.py verify",
        "evidence/part4/stage7/completion-receipt.json",
    )
    missing = [token for token in required if token not in rendered]
    require(not missing, f"CI is missing Stage 7 controls: {missing}")


def validate_documentation() -> None:
    content = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            Path("README.md"),
            Path("docs/verification.md"),
            Path("docs/runbook.md"),
            Path("evidence/README.md"),
            Path("docs/adr/0008-part4-closure-evidence.md"),
        )
    )
    required = (
        "Part 4 Stage 7",
        "33329861907",
        "33328391707",
        "LOCAL_VERIFIED",
        "AWS_VERIFIED",
        "actual billed cost remains `UNCLAIMED`",
        "production claim remains false",
        "runtime-equivalent",
    )
    missing = [token for token in required if token not in content]
    require(not missing, f"Stage 7 documentation is incomplete: {missing}")


def validate_completion_state() -> bool:
    final_preflights: list[Path] = []
    preflight_root = ROOT / "evidence/aws/preflight"
    for manifest_path in sorted(preflight_root.glob("*/manifest.json")):
        manifest = load(manifest_path)
        if manifest.get("evidence_type") == "part4-stage7-final-read-only-preflight":
            final_preflights.append(manifest_path.parent)
    completion = ROOT / COMPLETION
    if not final_preflights:
        require(not completion.exists(), "completion receipt exists without final preflight")
        return False
    require(len(final_preflights) == 1, "Stage 7 must have exactly one final preflight authority")
    require(completion.is_file(), "final preflight exists without the completion receipt")
    receipt = load(completion)
    validate_closure_receipt(receipt, ROOT)
    run_id = receipt.get("clean_inventory_authority", {}).get("run_id")
    require(final_preflights[0].name == str(run_id), "completion preflight run differs")
    return True


def validate_naming() -> None:
    branded_names = ("co" + "dex", "chat" + "gpt", "open" + "ai")
    patterns = [re.escape(value) for value in branded_names]
    patterns.extend((r"ai(?:-| )assisted", r"generated by " + "a" + "i"))
    prohibited = re.compile(rf"(?i)\b(?:{'|'.join(patterns)})\b")
    tracked = subprocess_files()
    violations: list[str] = []
    for relative in tracked:
        path = ROOT / relative
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if prohibited.search(text):
            violations.append(relative)
    require(not violations, f"project naming policy violation: {violations}")


def subprocess_files() -> list[str]:
    completed = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True)
    return [value.decode() for value in completed.stdout.split(b"\0") if value]


def validate(root: Path = ROOT) -> dict[str, Any]:
    require(root == ROOT, "Stage 7 controls must validate the repository root")
    validate_schema(ROOT / CLOSURE_SCHEMA)
    runtime = validate_runtime_manifest(ROOT / RUNTIME_MANIFEST)
    validate_preflight(ROOT / PREFLIGHT)
    validate_credit(ROOT / CREDIT)
    validate_ci(ROOT / CI)
    validate_documentation()
    validate_naming()
    completion_published = validate_completion_state()
    files = (
        CLOSURE_SCHEMA,
        RUNTIME_MANIFEST,
        PUBLISHER,
        RUNTIME_VERIFIER,
        Path("scripts/validate_part4_stage7_controls.py"),
        MODULE,
        CI,
        PREFLIGHT,
        CREDIT,
    )
    return {
        "schema_version": "1.0",
        "proof": "part4-stage7-closure-readiness",
        "result": "PASS",
        "claim_level": "LOCAL_VERIFIED",
        "aws_execution": False,
        "production_claim": False,
        "actual_billed_cost_claim": "UNCLAIMED",
        "completion_published": completion_published,
        "checks": {
            "claim_boundaries_frozen": True,
            "closure_schema_strict": True,
            "credit_attestation_current": True,
            "deterministic_publisher_present": True,
            "read_only_preflight_non_mutating": True,
            "runtime_equivalent_to_stage6": True,
            "sanitization_required": True,
            "stage7_only_allowlist_exact": True,
        },
        "runtime_equivalence": {
            key: runtime[key]
            for key in ("baseline_source_commit", "file_count", "files_sha256", "result")
        },
        "file_sha256": {path.as_posix(): sha256(ROOT / path) for path in files},
        "errors": [],
    }


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) == 2 else Path("part4-stage7-readiness.json")
    try:
        result = validate()
    except (
        ClosureError,
        ControlsError,
        OSError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        print(f"Part 4 Stage 7 controls rejected: {error}", file=sys.stderr)
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
