from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlasretail.part4_stage6_prerequisites import (
    PrerequisiteContext,
    PrerequisiteError,
    build_prerequisite_receipt,
    validate_prerequisite_receipt,
)

COMMIT = "a" * 40
REPOSITORY = "bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform"
REF = "refs/heads/main"


def write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def identity(run_id: str) -> dict[str, object]:
    return {
        "aws_account_id": "857229544428",
        "aws_region": "ap-southeast-2",
        "github_run_id": run_id,
        "oidc_role_arn": "arn:aws:iam::857229544428:role/AtlasRetailGitHubOidcRole",
        "project": "AtlasRetail",
        "ref": REF,
        "repository": REPOSITORY,
        "result": "PASS",
        "run_ceiling_usd": 5,
        "schema_version": "1.0",
        "source_commit": COMMIT,
        "terraform_state_key": "atlasretail/main.tfstate",
    }


def valid_inputs(tmp_path: Path) -> tuple[Path, Path, Path, PrerequisiteContext]:
    preflight = tmp_path / "preflight"
    glue = tmp_path / "glue"
    plan = tmp_path / "plan"
    write(preflight / "source-identity.json", identity("101"))
    write(
        preflight / "preflight.json",
        {
            "result": "PASS",
            "terraform_state_resources": [],
            "unexpected_resources": [],
            "errors": [],
        },
    )
    write(glue / "source-identity.json", identity("102"))
    write(
        glue / "phase-4-summary.json",
        {
            "result": "PASS",
            "claim": "AWS_GLUE_DEFINITION_CAPABILITY_VERIFIED",
            "source_commit": COMMIT,
            "run_id": "102",
            "workload_started": False,
            "aws_verified": {"independent_cleanup": True},
        },
    )
    write(plan / "source-identity.json", identity("103"))
    write(
        plan / "summary.json", {"result": "PASS", "source_commit": COMMIT, "github_run_id": "103"}
    )
    write(
        plan / "terraform-plan-validation.json",
        {
            "result": "PASS",
            "exact_envelope": True,
            "resource_count": 40,
            "read_only_data_source_counts": {"aws_iam_policy_document": 6},
        },
    )
    write(plan / "no-change-verification.json", {"result": "PASS"})
    return (
        preflight,
        glue,
        plan,
        PrerequisiteContext(
            source_commit=COMMIT,
            repository=REPOSITORY,
            ref=REF,
            preflight_run_id="101",
            glue_probe_run_id="102",
            plan_run_id="103",
        ),
    )


def build(tmp_path: Path) -> dict[str, object]:
    preflight, glue, plan, context = valid_inputs(tmp_path)
    return build_prerequisite_receipt(
        preflight_dir=preflight,
        glue_probe_dir=glue,
        plan_dir=plan,
        context=context,
    )


def test_exact_current_source_prerequisites_are_self_bound(tmp_path: Path) -> None:
    first = build(tmp_path)
    validate_prerequisite_receipt(first)
    assert first["result"] == "PASS"
    assert first["errors"] == []
    assert first["prerequisite_runs"] == {
        "read_only_preflight": "101",
        "glue_capability_probe": "102",
        "plan_only_proof": "103",
    }


def test_artifact_byte_change_changes_receipt_digest(tmp_path: Path) -> None:
    preflight, glue, plan, context = valid_inputs(tmp_path)
    first = build_prerequisite_receipt(
        preflight_dir=preflight, glue_probe_dir=glue, plan_dir=plan, context=context
    )
    write(plan / "additional-proof.json", {"result": "PASS"})
    second = build_prerequisite_receipt(
        preflight_dir=preflight, glue_probe_dir=glue, plan_dir=plan, context=context
    )
    assert first["receipt_sha256"] != second["receipt_sha256"]


def test_stale_source_and_weakened_plan_fail_closed(tmp_path: Path) -> None:
    preflight, glue, plan, context = valid_inputs(tmp_path)
    glue_summary = json.loads((glue / "phase-4-summary.json").read_text(encoding="utf-8"))
    glue_summary["source_commit"] = "b" * 40
    write(glue / "phase-4-summary.json", glue_summary)
    validation = json.loads((plan / "terraform-plan-validation.json").read_text(encoding="utf-8"))
    validation["exact_envelope"] = False
    write(plan / "terraform-plan-validation.json", validation)
    result = build_prerequisite_receipt(
        preflight_dir=preflight, glue_probe_dir=glue, plan_dir=plan, context=context
    )
    assert result["result"] == "FAIL"
    assert "Glue probe source mismatch" in result["errors"]
    assert "plan exact envelope was not enforced" in result["errors"]
    with pytest.raises(PrerequisiteError, match="did not pass"):
        validate_prerequisite_receipt(result)


def test_receipt_mutation_is_rejected(tmp_path: Path) -> None:
    receipt = build(tmp_path)
    receipt["prerequisite_runs"]["plan_only_proof"] = "999"  # type: ignore[index]
    with pytest.raises(PrerequisiteError, match="digest differs"):
        validate_prerequisite_receipt(receipt)


def test_symlinked_prerequisite_content_is_rejected(tmp_path: Path) -> None:
    preflight, glue, plan, context = valid_inputs(tmp_path)
    (plan / "linked-proof.json").symlink_to(plan / "summary.json")
    result = build_prerequisite_receipt(
        preflight_dir=preflight, glue_probe_dir=glue, plan_dir=plan, context=context
    )
    assert result["result"] == "FAIL"
    assert any("symbolic links are prohibited" in error for error in result["errors"])
