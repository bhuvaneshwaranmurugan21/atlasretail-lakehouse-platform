#!/usr/bin/env python3
"""Validate repository-only Part 4 Stage 5 teardown and recovery controls."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, NoReturn

import yaml

from atlasretail.part4_contract import validate_part4_contract_file
from atlasretail.part4_teardown_authority import TOP_LEVEL_KEYS
from atlasretail.terraform_envelope import EXPECTED_DATA_ADDRESSES, EXPECTED_MANAGED_ADDRESSES

ROOT = Path(__file__).resolve().parents[1]
BOUNDED_WORKFLOW = Path(".github/workflows/aws-bounded-lab.yml")
RECOVERY_WORKFLOW = Path(".github/workflows/aws-bounded-lab-recovery.yml")
AUTHORITY_SCHEMA = Path("contracts/part4/teardown-authority.schema.json")


class ControlsError(ValueError):
    """Raised when Stage 5 teardown authority is incomplete or weakened."""


def fail(message: str) -> NoReturn:
    raise ControlsError(message)


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


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


def load_workflow(path: Path) -> dict[str, Any]:
    value = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    if not isinstance(value, dict):
        fail(f"{path}: workflow must be a YAML object")
    return value


def validate_schema(path: Path) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    properties = value.get("properties") if isinstance(value, dict) else None
    require(value.get("type") == "object", "authority schema must describe an object")
    require(
        value.get("additionalProperties") is False,
        "authority schema must reject unknown top-level properties",
    )
    require(isinstance(properties, dict), "authority schema properties are absent")
    require(
        set(value.get("required", [])) == set(properties),
        "authority schema must require every top-level property",
    )
    require(set(properties) == TOP_LEVEL_KEYS, "authority schema and implementation keys differ")
    for name in ("aws", "bindings", "bounds", "lease", "terraform", "workflow"):
        nested = properties.get(name, {})
        require(
            nested.get("additionalProperties") is False,
            f"authority schema {name} must reject unknown properties",
        )
        require(
            set(nested.get("required", [])) == set(nested.get("properties", {})),
            f"authority schema {name} must require every property",
        )
    terraform = properties["terraform"]["properties"]
    require(
        terraform["managed_addresses"].get("minItems")
        == terraform["managed_addresses"].get("maxItems")
        == 40,
        "authority schema must freeze 40 managed addresses",
    )
    require(
        set(terraform["managed_addresses"].get("items", {}).get("enum", []))
        == EXPECTED_MANAGED_ADDRESSES,
        "authority schema managed address values differ",
    )
    require(
        terraform["read_only_data_addresses"].get("minItems")
        == terraform["read_only_data_addresses"].get("maxItems")
        == 6,
        "authority schema must freeze six read-only data addresses",
    )
    require(
        set(terraform["read_only_data_addresses"].get("items", {}).get("enum", []))
        == EXPECTED_DATA_ADDRESSES,
        "authority schema read-only data address values differ",
    )


def validate_bounded_workflow(path: Path) -> None:
    workflow = load_workflow(path)
    rendered = path.read_text(encoding="utf-8")
    execute = steps(workflow, "execute")
    teardown = steps(workflow, "teardown")
    ordered_execute = (
        index(execute, "Create and validate the saved apply plan"),
        index(execute, "Build and independently validate immutable teardown authority"),
        index(execute, "Persist immutable attempt-bound teardown authority before apply"),
        index(execute, "Bind persisted authority to the exact account lease"),
        index(execute, "Apply only the validated saved plan"),
    )
    require(
        list(ordered_execute) == sorted(ordered_execute),
        "authority must be validated, persisted and lease-bound before apply",
    )
    require(
        index(teardown, "Validate teardown authority")
        < index(teardown, "Initialize backend for admitted cleanup")
        < index(teardown, "Create and validate the saved destroy-only plan")
        < index(teardown, "Apply only the validated saved destroy plan"),
        "teardown must validate authority before backend plan and saved-plan apply",
    )
    required = (
        "--exact-envelope",
        "apply-outcome.json",
        "atlasretail-part4-teardown-authority-${{ github.run_id }}-${{ github.run_attempt }}",
        "atlasretail-pre-teardown-${{ github.run_id }}-${{ github.run_attempt }}",
        "retention-days: 30",
        "--artifact-digest",
        "AUTHORITY_BOUND",
        "--allow-authority-bound-plan-digests",
        "teardown-authority-recovery-verification.json",
        "teardown-lease-authority-verification.json",
        "state_has_resources",
        "steps.backend.outputs.state_has_resources != 'true'",
        "--authority-sha256",
        "--run-attempt",
        "--source-commit",
    )
    missing = [token for token in required if token not in rendered]
    require(not missing, f"bounded workflow is missing Stage 5 controls: {missing}")
    require(
        rendered.count("finalize_part4_evidence.py") == 1,
        "bounded workflow must retain exactly one final evidence authority",
    )
    require(
        "${GITHUB_REPOSITORY}/${GITHUB_RUN_ID}/${GITHUB_RUN_ATTEMPT}" in rendered,
        "bounded workflow lease is not attempt-bound",
    )


def validate_recovery_workflow(path: Path) -> None:
    workflow = load_workflow(path)
    rendered = path.read_text(encoding="utf-8")
    require(set(workflow.get("on", {})) == {"workflow_dispatch"}, "recovery must be manual only")
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    require(
        set(inputs)
        == {"confirm_recovery", "failed_run_attempt", "failed_run_id", "failed_source_commit"},
        "recovery inputs are not exact failed-attempt bindings",
    )
    job = workflow.get("jobs", {}).get("recover", {})
    require(job.get("if") == "github.ref == 'refs/heads/main'", "recovery is not main-only")
    recovery_steps = steps(workflow, "recover")
    authority = index(
        recovery_steps, "Independently validate immutable recovery authority before AWS access"
    )
    credentials = credential_index(recovery_steps)
    lease = index(recovery_steps, "Prove live identity and bind recovery to the exact failed lease")
    initialize = index(
        recovery_steps, "Initialize only the failed source backend and recover identifiers"
    )
    plan = index(recovery_steps, "Create and validate the saved recovery destroy-only plan")
    apply = index(recovery_steps, "Apply only the independently validated saved recovery plan")
    teardown = index(recovery_steps, "Prove recovery teardown across AWS and Terraform inventories")
    release = index(recovery_steps, "Release only the exact verified recovery lease")
    cleanup = index(recovery_steps, "Remove ephemeral recovery outputs")
    summary = index(recovery_steps, "Build the strict cleanup-only recovery evidence summary")
    require(
        authority
        < credentials
        < lease
        < initialize
        < plan
        < apply
        < teardown
        < release
        < cleanup
        < summary,
        "recovery control ordering is unsafe",
    )
    required = (
        "RECOVER_ATLASRETAIL_PART4",
        "refs/heads/main",
        "atlasretail-part4-teardown-authority-${{ inputs.failed_run_id }}-"
        "${{ inputs.failed_run_attempt }}",
        "run-id: ${{ inputs.failed_run_id }}",
        "atlasretail-pre-teardown-${{ inputs.failed_run_id }}-${{ inputs.failed_run_attempt }}",
        "--mode teardown",
        "--allow-authority-bound-plan-digests",
        "manage_part4_lease.py recover",
        "--allow-partial-destroy",
        "recovery-destroy.tfplan",
        "sha256sum infra/atlas/recovery-destroy.tfplan",
        "verify_teardown.py",
        "steps.verify_teardown.outcome == 'success'",
        "steps.verify_no_deployment.outcome == 'success'",
        "recovery-clean-no-deployment.json",
        "steps.backend.outputs.state_has_resources == 'true'",
        "summarize_part4_recovery.py",
        '"workload_execution": False',
    )
    missing = [token for token in required if token not in rendered]
    require(not missing, f"recovery workflow is missing Stage 5 controls: {missing}")
    forbidden = (
        "atlasretail generate-sources",
        "aws stepfunctions start-execution",
        "aws glue start-job-run",
        "aws athena start-query-execution",
        "aws lambda invoke",
        "terraform apply -auto-approve -var",
    )
    present = [token for token in forbidden if token in rendered]
    require(not present, f"recovery workflow contains workload/create behavior: {present}")


def validate_lease_source(path: Path) -> None:
    rendered = path.read_text(encoding="utf-8")
    require(
        '"attribute_not_exists(lock_id)"' in rendered,
        "lease acquisition must be conditional on absence",
    )
    require("expires_at <" not in rendered, "lease must not permit silent expiry takeover")
    for token in (
        "AUTHORITY_BOUND",
        "RECOVERY_BOUND",
        "EXACT_OWNER_TRANSITION",
        "ABSENT_LEASE_RECOVERY_ACQUISITION",
        "authority_sha256",
        "run_attempt",
        "source_commit",
        "--consistent-read",
    ):
        require(token in rendered, f"lease controller is missing {token}")


def validate(repo_root: Path) -> dict[str, Any]:
    contract = validate_part4_contract_file(
        repo_root / "contracts/part4/run-contract.json", repo_root=repo_root
    )
    schema = repo_root / AUTHORITY_SCHEMA
    validate_schema(schema)
    validate_bounded_workflow(repo_root / BOUNDED_WORKFLOW)
    validate_recovery_workflow(repo_root / RECOVERY_WORKFLOW)
    validate_lease_source(repo_root / "scripts/manage_part4_lease.py")
    require(len(EXPECTED_MANAGED_ADDRESSES) == 40, "managed address envelope changed")
    require(len(EXPECTED_DATA_ADDRESSES) == 6, "data-source address envelope changed")
    evidence_source = (repo_root / "src/atlasretail/part4_evidence.py").read_text(encoding="utf-8")
    require(
        evidence_source.count('"claim_level": "AWS_VERIFIED"') == 1,
        "AWS_VERIFIED must retain one normal-run finalizer authority",
    )
    files = (
        repo_root / AUTHORITY_SCHEMA,
        repo_root / BOUNDED_WORKFLOW,
        repo_root / RECOVERY_WORKFLOW,
        repo_root / "src/atlasretail/part4_teardown_authority.py",
        repo_root / "src/atlasretail/terraform_envelope.py",
        repo_root / "scripts/build_part4_teardown_authority.py",
        repo_root / "scripts/validate_part4_teardown_authority.py",
        repo_root / "scripts/manage_part4_lease.py",
        repo_root / "scripts/summarize_part4_recovery.py",
        repo_root / "scripts/validate_part4_stage5_controls.py",
        repo_root / "scripts/verify_lease_release.py",
        repo_root / "src/atlasretail/part4_evidence.py",
    )
    implementation_sha = hashlib.sha256(b"".join(path.read_bytes() for path in files)).hexdigest()
    return {
        "aws_execution": False,
        "claim_level": "LOCAL_VERIFIED",
        "contract_sha256": contract.contract_sha256,
        "proof": "part4-stage5-immutable-teardown-authority",
        "result": "PASS",
        "authority_schema_sha256": hashlib.sha256(schema.read_bytes()).hexdigest(),
        "implementation_sha256": implementation_sha,
        "managed_address_count": 40,
        "read_only_data_address_count": 6,
        "normal_workflow_sha256": hashlib.sha256(
            (repo_root / BOUNDED_WORKFLOW).read_bytes()
        ).hexdigest(),
        "recovery_workflow_sha256": hashlib.sha256(
            (repo_root / RECOVERY_WORKFLOW).read_bytes()
        ).hexdigest(),
        "target_sha256": contract.target_sha256,
    }


def main() -> int:
    if len(sys.argv) > 2:
        print("usage: validate_part4_stage5_controls.py [OUTPUT_JSON]", file=sys.stderr)
        return 2
    output = Path(sys.argv[1]) if len(sys.argv) == 2 else None
    try:
        result = validate(ROOT)
    except (ControlsError, KeyError, OSError, TypeError, ValueError) as error:
        print(f"Part 4 Stage 5 controls rejected: {error}", file=sys.stderr)
        return 1
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(rendered, end="")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
