#!/usr/bin/env python3
"""Validate repository-only Part 4 Stage 4 evidence-readiness controls."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, NoReturn

import yaml

from atlasretail.part4_contract import (
    REQUIRED_EVIDENCE_DOMAINS,
    REQUIRED_PROVENANCE_FIELDS,
    validate_part4_contract_file,
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = Path(".github/workflows/aws-bounded-lab.yml")
SCHEMAS = (
    Path("contracts/part4/execution-checkpoint.schema.json"),
    Path("contracts/part4/final-evidence.schema.json"),
)


class ControlsError(ValueError):
    """Raised when Stage 4 evidence readiness is incomplete or weakened."""


def fail(message: str) -> NoReturn:
    raise ControlsError(message)


def step_index(steps: list[dict[str, Any]], name: str) -> int:
    try:
        return next(index for index, step in enumerate(steps) if step.get("name") == name)
    except StopIteration as error:
        raise ControlsError(f"workflow step is missing: {name}") from error


def _load_policy(repo_root: Path) -> Any:
    path = repo_root / "scripts/build_part4_session_policy.py"
    spec = importlib.util.spec_from_file_location("part4_stage4_session_policy", path)
    if spec is None or spec.loader is None:
        fail("unable to load Part 4 session policy builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _validate_schema(path: Path, proof: str) -> str:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        fail(f"{path}: schema must be an object")
    if value.get("type") != "object" or value.get("additionalProperties") is not False:
        fail(f"{path}: schema must reject unknown top-level properties")
    properties = value.get("properties")
    if not isinstance(properties, dict) or properties.get("proof", {}).get("const") != proof:
        fail(f"{path}: schema has the wrong proof identity")
    required = value.get("required")
    if not isinstance(required, list) or set(required) != set(properties):
        fail(f"{path}: every top-level property must be required")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(repo_root: Path) -> dict[str, Any]:
    contract = validate_part4_contract_file(
        repo_root / "contracts/part4/run-contract.json", repo_root=repo_root
    )
    schema_hashes = {
        path.name: _validate_schema(repo_root / path, proof)
        for path, proof in zip(
            SCHEMAS,
            ("part4-execution-checkpoint", "part4-final-evidence"),
            strict=True,
        )
    }
    workflow_path = repo_root / WORKFLOW
    rendered = workflow_path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(rendered)
    jobs = parsed.get("jobs", {}) if isinstance(parsed, dict) else {}
    execute = jobs.get("execute", {}).get("steps", [])
    teardown = jobs.get("teardown", {}).get("steps", [])
    if not isinstance(execute, list) or not isinstance(teardown, list):
        fail("workflow execute/teardown steps are invalid")
    if step_index(execute, "Verify the deployed control plane before any workload") >= step_index(
        execute, "Upload only the admitted immutable inputs"
    ):
        fail("deployed inventory must be verified before workload input upload")
    if step_index(execute, "Collect AWS execution and CloudWatch evidence") >= step_index(
        execute, "Persist evidence before teardown"
    ):
        fail("execution checkpoint must precede pre-teardown persistence")
    teardown_proof = step_index(teardown, "Prove teardown across AWS and Terraform inventories")
    lease_release = step_index(teardown, "Release only a verified clean run's account-wide lease")
    finalization = step_index(teardown, "Finalize only complete execution and teardown evidence")
    if not teardown_proof < lease_release < finalization:
        fail("finalization must follow teardown proof and verified lease release")
    required_workflow_tokens = {
        "validate_part4_execution_evidence.py",
        "finalize_part4_evidence.py",
        "verify_lease_release.py",
        "execution-session-receipt.json",
        "teardown-session-receipt.json",
        "cloudwatch-export-receipt.json",
        "deployment-verification.json",
        "post-teardown-budget-verification.json",
        "inline-session-policy",
    }
    missing = sorted(token for token in required_workflow_tokens if token not in rendered)
    if missing:
        fail(f"workflow evidence controls are missing: {missing}")
    if "summarize_aws_evidence.py" in rendered:
        fail("workflow still invokes the retired pre-teardown summarizer")
    if rendered.count("finalize_part4_evidence.py") != 1:
        fail("workflow must have exactly one final evidence authority")

    policy = _load_policy(repo_root)
    for mode in ("execution", "teardown"):
        document = policy.render_policy(mode)
        if len(document) > policy.MAX_PACKED_RISK:
            fail(f"{mode} session policy exceeds packed-size risk budget")
        forbidden_region = "ap-" + "south-1"
        if "ap-southeast-2" not in document or forbidden_region in document:
            fail(f"{mode} session policy is not exact-region bound")
    evidence_source = (repo_root / "src/atlasretail/part4_evidence.py").read_text(encoding="utf-8")
    if evidence_source.count('"claim_level": "AWS_VERIFIED"') != 1:
        fail("AWS_VERIFIED must have exactly one finalizer authority")
    for domain in REQUIRED_EVIDENCE_DOMAINS:
        if f'"{domain}"' not in evidence_source:
            fail(f"evidence implementation does not name required domain {domain}")
    if len(REQUIRED_PROVENANCE_FIELDS) != 17 or len(REQUIRED_EVIDENCE_DOMAINS) != 20:
        fail("frozen contract cardinalities changed")
    source_files = (
        repo_root / "src/atlasretail/part4_evidence.py",
        repo_root / "scripts/validate_part4_execution_evidence.py",
        repo_root / "scripts/finalize_part4_evidence.py",
        repo_root / "scripts/verify_lease_release.py",
        repo_root / "scripts/build_part4_session_policy.py",
    )
    implementation_sha = hashlib.sha256(
        b"".join(path.read_bytes() for path in source_files)
    ).hexdigest()
    return {
        "aws_execution": False,
        "claim_level": "LOCAL_VERIFIED",
        "contract_sha256": contract.contract_sha256,
        "evidence_domain_count": 20,
        "implementation_sha256": implementation_sha,
        "proof": "part4-stage4-contract-complete-evidence-readiness",
        "provenance_field_count": 17,
        "result": "PASS",
        "schema_sha256": schema_hashes,
        "target_sha256": contract.target_sha256,
        "workflow_sha256": hashlib.sha256(workflow_path.read_bytes()).hexdigest(),
    }


def main() -> int:
    if len(sys.argv) > 2:
        print("usage: validate_part4_stage4_controls.py [OUTPUT_JSON]", file=sys.stderr)
        return 2
    output = Path(sys.argv[1]) if len(sys.argv) == 2 else None
    try:
        result = validate(ROOT)
    except (ControlsError, KeyError, OSError, TypeError, ValueError) as error:
        print(f"Part 4 Stage 4 controls rejected: {error}", file=sys.stderr)
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
