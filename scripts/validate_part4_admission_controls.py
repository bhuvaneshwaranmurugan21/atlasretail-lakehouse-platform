#!/usr/bin/env python3
"""Validate and summarize the repository-only Part 4 Stage 3 admission controls."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, NoReturn

import yaml

from atlasretail.part4_admission import (
    ADMISSION_SCHEMA_RELATIVE_PATH,
    AdmissionError,
    validate_admission_schema_file,
)
from atlasretail.part4_contract import CONTRACT_RELATIVE_PATH, validate_part4_contract_file

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = Path(".github/workflows/aws-bounded-lab.yml")


def fail(path: str, observed: object, required: object) -> NoReturn:
    raise AdmissionError(f"{path}: observed {observed!r}; required {required!r}")


def require(path: str, observed: object, required: object) -> None:
    if observed != required:
        fail(path, observed, required)


def credential_index(steps: list[dict[str, Any]]) -> int:
    return next(
        index
        for index, step in enumerate(steps)
        if "aws-actions/configure-aws-credentials@" in str(step.get("uses", ""))
    )


def validation_index(steps: list[dict[str, Any]]) -> int:
    return next(
        index
        for index, step in enumerate(steps)
        if "validate_part4_admission.py" in str(step.get("run", ""))
    )


def validate(repo_root: Path) -> dict[str, Any]:
    workflow_path = repo_root / WORKFLOW
    rendered = workflow_path.read_text(encoding="utf-8")
    parsed = yaml.load(rendered, Loader=yaml.BaseLoader)
    if not isinstance(parsed, dict):
        fail("workflow", type(parsed).__name__, "YAML object")
    require("workflow.triggers", set(parsed["on"]), {"workflow_dispatch"})
    inputs = parsed["on"]["workflow_dispatch"]["inputs"]
    require(
        "workflow.inputs",
        set(inputs),
        {"budget_ceiling_usd", "confirm_destroy", "confirm_execute", "order_count"},
    )
    require("workflow.inputs.order_count.default", inputs["order_count"].get("default"), "500")
    require(
        "workflow.inputs.budget_ceiling_usd.default",
        inputs["budget_ceiling_usd"].get("default"),
        "5",
    )
    require(
        "workflow.inputs.confirm_execute.default",
        "default" in inputs["confirm_execute"],
        False,
    )
    require(
        "workflow.inputs.confirm_destroy.default",
        "default" in inputs["confirm_destroy"],
        False,
    )
    require("workflow.permissions", parsed.get("permissions"), {"contents": "read"})
    jobs = parsed["jobs"]
    require("workflow.jobs", set(jobs), {"admission", "execute", "teardown"})
    admission = jobs["admission"]
    require("workflow.admission.permissions", admission["permissions"], {"contents": "read"})
    admission_text = "\n".join(
        str(step.get("uses", "")) + "\n" + str(step.get("run", "")) for step in admission["steps"]
    )
    for forbidden in ("configure-aws-credentials", "aws ", "terraform"):
        if forbidden in admission_text:
            fail("workflow.admission", forbidden, "no AWS or Terraform reachability")
    expected_permissions = {"actions": "read", "contents": "read", "id-token": "write"}
    require("workflow.execute.needs", jobs["execute"].get("needs"), "admission")
    require("workflow.execute.permissions", jobs["execute"]["permissions"], expected_permissions)
    require(
        "workflow.teardown.needs",
        jobs["teardown"].get("needs"),
        ["admission", "execute"],
    )
    require(
        "workflow.teardown.if",
        jobs["teardown"].get("if"),
        "${{ always() && needs.admission.result == 'success' }}",
    )
    require("workflow.teardown.permissions", jobs["teardown"]["permissions"], expected_permissions)
    for name in ("execute", "teardown"):
        steps = jobs[name]["steps"]
        if validation_index(steps) >= credential_index(steps):
            fail(f"workflow.{name}.ordering", "credentials before admission", "admission first")
    require(
        "workflow.admission_revalidation_count",
        rendered.count("validate_part4_admission.py"),
        4,
    )
    require("workflow.source_generation_count", rendered.count("atlasretail generate-sources"), 1)
    if ".artifacts/aws" in rendered:
        fail("workflow.source_handoff", ".artifacts/aws", "admitted source directory only")
    if "--managed-manifest-output" not in rendered:
        fail("workflow.managed_manifest", "missing", "derived output outside admitted tree")
    artifact = "atlasretail-part4-admission-${{ github.run_id }}-${{ github.run_attempt }}"
    require("workflow.admission_artifact_count", rendered.count(artifact), 3)
    release = next(
        step for step in jobs["teardown"]["steps"] if "Release only" in str(step.get("name", ""))
    )
    release_if = str(release.get("if", ""))
    for required in (
        "steps.verify_teardown.outcome == 'success'",
        "steps.verify_no_deployment.outcome == 'success'",
    ):
        if required not in release_if:
            fail("workflow.lease_release", release_if, required)
    contract = validate_part4_contract_file(repo_root / CONTRACT_RELATIVE_PATH, repo_root=repo_root)
    schema_sha256 = validate_admission_schema_file(repo_root / ADMISSION_SCHEMA_RELATIVE_PATH)
    return {
        "admission_schema_sha256": schema_sha256,
        "aws_execution": False,
        "claim_level": "LOCAL_VERIFIED",
        "contract_sha256": contract.contract_sha256,
        "proof": "part4-stage3-pre-aws-admission-controls",
        "result": "PASS",
        "target_sha256": contract.target_sha256,
        "workflow_sha256": hashlib.sha256(workflow_path.read_bytes()).hexdigest(),
    }


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) == 2 else None
    if len(sys.argv) > 2:
        print("usage: validate_part4_admission_controls.py [OUTPUT_JSON]", file=sys.stderr)
        return 2
    try:
        result = validate(ROOT)
    except (AdmissionError, KeyError, OSError, StopIteration, TypeError) as error:
        print(f"Part 4 admission controls rejected: {error}", file=sys.stderr)
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
