#!/usr/bin/env python3
"""Validate repository-only Part 4 Stage 6 managed-execution controls."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn

import yaml

ROOT = Path(__file__).resolve().parents[1]
BOUNDED = Path(".github/workflows/aws-bounded-lab.yml")
LEASE_RECOVERY = Path(".github/workflows/aws-bounded-lab-lease-recovery.yml")
CONTRACT = Path("contracts/part4/run-contract.json")
ADMISSION_SCHEMA = Path("contracts/part4/admission-receipt.schema.json")
PREREQUISITE_SCHEMA = Path("contracts/part4/stage6-prerequisite-admission.schema.json")
PREREQUISITES = Path("src/atlasretail/part4_stage6_prerequisites.py")
LEASE = Path("scripts/manage_part4_lease.py")
LEASE_RELEASE = Path("scripts/verify_lease_release.py")
EXPRESSION = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)


class ControlsError(ValueError):
    """Raised when a Stage 6 control is missing or weakened."""


def fail(message: str) -> NoReturn:
    raise ControlsError(message)


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def load_workflow(path: Path) -> dict[str, Any]:
    value = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    if not isinstance(value, dict):
        fail(f"{path}: workflow must be a YAML object")
    return value


def steps(workflow: dict[str, Any], job: str) -> list[dict[str, Any]]:
    value = workflow.get("jobs", {}).get(job, {}).get("steps")
    if not isinstance(value, list) or not all(isinstance(step, dict) for step in value):
        fail(f"workflow job {job} has invalid steps")
    return value


def index(values: list[dict[str, Any]], name: str) -> int:
    try:
        return next(position for position, value in enumerate(values) if value.get("name") == name)
    except StopIteration as error:
        raise ControlsError(f"workflow step is missing: {name}") from error


def credential_index(values: list[dict[str, Any]]) -> int:
    try:
        return next(
            position
            for position, value in enumerate(values)
            if "aws-actions/configure-aws-credentials@" in str(value.get("uses", ""))
        )
    except StopIteration as error:
        raise ControlsError("workflow credential step is missing") from error


def run_blocks(value: Any, location: str = "workflow") -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_location = f"{location}.{key}"
            if key == "run" and isinstance(child, str):
                result.append((child_location, child))
            else:
                result.extend(run_blocks(child, child_location))
    elif isinstance(value, list):
        for position, child in enumerate(value):
            result.extend(run_blocks(child, f"{location}[{position}]"))
    return result


def validate_shell(root: Path) -> int:
    count = 0
    for path in sorted((root / ".github/workflows").glob("*.yml")):
        workflow = load_workflow(path)
        for location, shell in run_blocks(workflow):
            count += 1
            completed = subprocess.run(
                ["bash", "-n"],
                input=EXPRESSION.sub("github_expression", shell),
                text=True,
                capture_output=True,
                check=False,
            )
            require(
                completed.returncode == 0,
                f"{path.relative_to(root)}:{location}: {completed.stderr.strip()}",
            )
    require(count > 0, "no workflow shell blocks were found")
    return count


def validate_bounded(path: Path) -> dict[str, int]:
    workflow = load_workflow(path)
    rendered = path.read_text(encoding="utf-8")
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    require(
        set(inputs)
        == {
            "budget_ceiling_usd",
            "confirm_destroy",
            "confirm_execute",
            "glue_probe_run_id",
            "order_count",
            "plan_run_id",
            "preflight_run_id",
        },
        "bounded workflow dispatch inputs do not bind the exact Stage 6 intent",
    )
    admission_job = workflow["jobs"]["admission"]
    admission_permissions = admission_job.get("permissions", {})
    require(admission_permissions.get("actions") == "read", "admission cannot read artifacts")
    require("id-token" not in admission_permissions, "admission must not request OIDC permission")
    admission = steps(workflow, "admission")
    prerequisite = index(admission, "Admit only current-source prerequisite evidence")
    source_admission = index(admission, "Admit the exact bounded run intent")
    require(prerequisite < source_admission, "prerequisites are not validated before run admission")
    for name in (
        "Download the exact read-only preflight prerequisite",
        "Download the exact Glue capability prerequisite",
        "Download the exact plan-only prerequisite",
    ):
        require(index(admission, name) < prerequisite, f"{name} is not validated before admission")

    execute_job = workflow["jobs"]["execute"]
    require(int(execute_job.get("timeout-minutes", "0")) <= 55, "execute exceeds OIDC lifetime")
    execute = steps(workflow, "execute")
    require(
        index(execute, "Revalidate admission before requesting AWS credentials")
        < credential_index(execute),
        "admission is not revalidated before execution OIDC",
    )
    teardown = steps(workflow, "teardown")
    require(
        index(teardown, "Revalidate teardown admission before requesting AWS credentials")
        < credential_index(teardown),
        "admission is not revalidated before teardown OIDC",
    )
    required = (
        "validate_part4_stage6_prerequisites.py",
        "--prerequisite-receipt",
        "role-duration-seconds: 3600",
        "allowed-account-ids:",
        "unset-current-credentials: true",
        "action-timeout-s: 120",
        "terraform-destroy-plan-digests.json",
        '"binary_sha256"',
        "saved destroy plan binding changed",
        'runtime_status="$?"',
        'finalizer_status="$?"',
        'test -s "${EVIDENCE_DIR}/final-summary.json"',
    )
    missing = [token for token in required if token not in rendered]
    require(not missing, f"bounded workflow is missing Stage 6 controls: {missing}")
    require(rendered.count("--prerequisite-receipt") == 5, "not every admission check is bound")
    return {
        "admission_step_count": len(admission),
        "execute_step_count": len(execute),
        "teardown_step_count": len(teardown),
    }


def validate_lease_recovery(path: Path) -> int:
    workflow = load_workflow(path)
    rendered = path.read_text(encoding="utf-8")
    require(
        set(workflow.get("on", {})) == {"workflow_dispatch"}, "lease recovery is not manual only"
    )
    job = workflow["jobs"].get("recover-lease", {})
    require(job.get("if") == "github.ref == 'refs/heads/main'", "lease recovery is not main-only")
    values = steps(workflow, "recover-lease")
    admission = index(values, "Validate failed admission and lease acquisition before AWS access")
    credentials = credential_index(values)
    clean = index(values, "Prove no deployment and the exact live-or-absent pre-authority lease")
    release = index(values, "Release only the exact verified pre-authority lease")
    summary = index(values, "Build strict lease-only recovery summary")
    require(
        admission < credentials < clean < release < summary, "lease recovery ordering is unsafe"
    )
    required = (
        "RELEASE_ATLASRETAIL_PART4_PREAUTHORITY_LEASE",
        "atlasretail-part4-admission-${{ inputs.failed_run_id }}-",
        "atlasretail-part4-lease-${{ inputs.failed_run_id }}-",
        "validate_part4_admission.py",
        "verify_preflight.py",
        "manage_part4_lease.py verify-acquired-or-absent",
        "ALLOW_ABSENT",
        "--expected-state ACQUIRED",
        "--allow-absent",
        '"workload_execution": False',
        '"terraform_apply": False',
        '"silent_expiry_takeover": False',
    )
    missing = [token for token in required if token not in rendered]
    require(not missing, f"lease recovery is missing Stage 6 controls: {missing}")
    forbidden = (
        "terraform apply",
        "start-execution",
        "start-job-run",
        "start-query-execution",
        "lambda invoke",
        "generate-sources",
    )
    present = [token for token in forbidden if token in rendered.lower()]
    require(not present, f"lease recovery contains mutation/workload behavior: {present}")
    return len(values)


def validate_contract(root: Path) -> None:
    contract = json.loads((root / CONTRACT).read_text(encoding="utf-8"))
    require(contract.get("version") == "1.1.0", "Stage 6 semantic contract version is absent")
    provenance = contract.get("evidence", {}).get("required_provenance_fields", [])
    require(
        "prerequisite_admission_sha256" in provenance,
        "final provenance does not require prerequisite admission",
    )
    schema = json.loads((root / ADMISSION_SCHEMA).read_text(encoding="utf-8"))
    require("prerequisites" in schema.get("required", []), "admission schema omits prerequisites")
    prerequisite = schema.get("properties", {}).get("prerequisites", {})
    require(prerequisite.get("additionalProperties") is False, "prerequisite binding is not strict")
    require(
        set(prerequisite.get("required", [])) == set(prerequisite.get("properties", {})),
        "prerequisite binding does not require every property",
    )
    stage6_schema = json.loads((root / PREREQUISITE_SCHEMA).read_text(encoding="utf-8"))
    require(
        stage6_schema.get("additionalProperties") is False,
        "Stage 6 prerequisite schema permits unknown properties",
    )
    require(
        set(stage6_schema.get("required", [])) == set(stage6_schema.get("properties", {})),
        "Stage 6 prerequisite schema does not require every property",
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(root: Path) -> dict[str, Any]:
    bounded = validate_bounded(root / BOUNDED)
    recovery_steps = validate_lease_recovery(root / LEASE_RECOVERY)
    validate_contract(root)
    shell_blocks = validate_shell(root)
    lease_source = (root / LEASE).read_text(encoding="utf-8")
    release_source = (root / LEASE_RELEASE).read_text(encoding="utf-8")
    require(
        "verify-acquired-or-absent" in lease_source,
        "idempotent pre-authority lease verification is absent",
    )
    require("authority_absent" in lease_source, "authority absence is not proved")
    for token in ("--contract-sha256", "--target-sha256", "--expected-state"):
        require(token in release_source, f"lease release is missing {token}")
    files = (
        BOUNDED,
        LEASE_RECOVERY,
        CONTRACT,
        ADMISSION_SCHEMA,
        PREREQUISITE_SCHEMA,
        PREREQUISITES,
        LEASE,
        LEASE_RELEASE,
    )
    return {
        "schema_version": "1.0",
        "proof": "part4-stage6-managed-execution-readiness",
        "result": "PASS",
        "claim_level": "LOCAL_VERIFIED",
        "aws_execution": False,
        "contract_version": "1.1.0",
        "checks": {
            "current_source_prerequisite_admission": True,
            "oidc_lifetime_bounded": True,
            "workflow_shell_syntax": True,
            "destroy_plan_binary_rechecked": True,
            "pre_authority_lease_recovery": True,
            "failure_summary_always_attempted": True,
        },
        "counts": {
            **bounded,
            "lease_recovery_step_count": recovery_steps,
            "workflow_shell_block_count": shell_blocks,
        },
        "file_sha256": {path.as_posix(): sha256(root / path) for path in files},
        "errors": [],
    }


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) == 2 else Path("part4-stage6-readiness.json")
    try:
        result = validate(ROOT)
    except (ControlsError, OSError, json.JSONDecodeError) as error:
        print(f"Part 4 Stage 6 controls rejected: {error}", file=sys.stderr)
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
