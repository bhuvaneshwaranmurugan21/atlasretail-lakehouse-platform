from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "summarize_deployment_evidence.py"
SPEC = importlib.util.spec_from_file_location("summarize_deployment_evidence", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def write_valid_evidence(directory: Path) -> None:
    write_json(
        directory / "deployment-verification.json",
        {
            "result": "PASS",
            "claim": "AWS_DEPLOYMENT_VERIFIED",
            "zero_workload": "PASS",
            "terraform_managed_resource_count": 40,
        },
    )
    write_json(directory / "teardown.json", {"result": "PASS"})
    write_json(
        directory / "terraform-apply-plan-validation.json",
        {
            "result": "PASS",
            "mode": "apply",
            "resource_count": 40,
            "read_only_data_source_counts": {"aws_iam_policy_document": 6},
        },
    )
    write_json(
        directory / "terraform-destroy-plan-validation.json",
        {"result": "PASS", "mode": "destroy", "resource_count": 40},
    )


def test_exact_part_3_contract_earns_claim(tmp_path: Path) -> None:
    write_valid_evidence(tmp_path)

    result = MODULE.summarize(tmp_path, "a" * 40, "123")

    assert result["schema_version"] == "1.1"
    assert result["part"] == "part-3"
    assert result["proof"] == "zero-workload-controlled-deployment"
    assert result["result"] == "PASS"
    assert result["claim"] == "AWS_DEPLOYMENT_VERIFIED"
    assert result["active_residue"] == 0
    assert result["errors"] == []
    assert all(result["checks"].values())


@pytest.mark.parametrize(
    ("filename", "field", "invalid_value", "expected_error"),
    [
        ("deployment-verification.json", "result", "FAIL", "DEPLOYMENT_NOT_VERIFIED"),
        ("deployment-verification.json", "claim", "NONE", "UPSTREAM_CLAIM_INVALID"),
        (
            "deployment-verification.json",
            "zero_workload",
            "FAIL",
            "ZERO_WORKLOAD_NOT_VERIFIED",
        ),
        (
            "deployment-verification.json",
            "terraform_managed_resource_count",
            39,
            "DEPLOYMENT_RESOURCE_COUNT_MISMATCH",
        ),
        (
            "terraform-apply-plan-validation.json",
            "result",
            "FAIL",
            "APPLY_PLAN_NOT_VERIFIED",
        ),
        (
            "terraform-apply-plan-validation.json",
            "mode",
            "destroy",
            "APPLY_PLAN_MODE_INVALID",
        ),
        (
            "terraform-apply-plan-validation.json",
            "resource_count",
            39,
            "APPLY_RESOURCE_COUNT_MISMATCH",
        ),
        (
            "terraform-apply-plan-validation.json",
            "read_only_data_source_counts",
            {"aws_iam_policy_document": 5},
            "APPLY_DATA_SOURCE_COUNT_MISMATCH",
        ),
        (
            "terraform-destroy-plan-validation.json",
            "result",
            "FAIL",
            "DESTROY_PLAN_NOT_VERIFIED",
        ),
        (
            "terraform-destroy-plan-validation.json",
            "mode",
            "apply",
            "DESTROY_PLAN_MODE_INVALID",
        ),
        (
            "terraform-destroy-plan-validation.json",
            "resource_count",
            39,
            "DESTROY_RESOURCE_COUNT_MISMATCH",
        ),
        ("teardown.json", "result", "FAIL", "TEARDOWN_NOT_VERIFIED"),
    ],
)
def test_any_failed_acceptance_gate_rejects_claim(
    tmp_path: Path,
    filename: str,
    field: str,
    invalid_value: object,
    expected_error: str,
) -> None:
    write_valid_evidence(tmp_path)
    path = tmp_path / filename
    value = json.loads(path.read_text(encoding="utf-8"))
    value[field] = invalid_value
    write_json(path, value)

    result = MODULE.summarize(tmp_path, "a" * 40, "123")

    assert result["result"] == "FAIL"
    assert result["claim"] == "NONE"
    assert expected_error in result["errors"]


@pytest.mark.parametrize(
    ("filename", "content", "expected_error"),
    [
        ("deployment-verification.json", None, "DEPLOYMENT_NOT_VERIFIED"),
        ("teardown.json", "not-json", "TEARDOWN_NOT_VERIFIED"),
        ("terraform-apply-plan-validation.json", "[]", "APPLY_PLAN_NOT_VERIFIED"),
        ("terraform-destroy-plan-validation.json", None, "DESTROY_PLAN_NOT_VERIFIED"),
    ],
)
def test_missing_or_malformed_evidence_rejects_claim(
    tmp_path: Path, filename: str, content: str | None, expected_error: str
) -> None:
    write_valid_evidence(tmp_path)
    path = tmp_path / filename
    path.unlink()
    if content is not None:
        path.write_text(content, encoding="utf-8")

    result = MODULE.summarize(tmp_path, "a" * 40, "123")

    assert result["result"] == "FAIL"
    assert result["claim"] == "NONE"
    assert expected_error in result["errors"]


@pytest.mark.parametrize(
    ("source_commit", "run_id", "expected_error"),
    [
        ("short", "123", "SOURCE_COMMIT_INVALID"),
        ("g" * 40, "123", "SOURCE_COMMIT_INVALID"),
        ("a" * 40, "0", "GITHUB_RUN_ID_INVALID"),
        ("a" * 40, "run-123", "GITHUB_RUN_ID_INVALID"),
    ],
)
def test_invalid_source_identity_rejects_claim(
    tmp_path: Path, source_commit: str, run_id: str, expected_error: str
) -> None:
    write_valid_evidence(tmp_path)

    result = MODULE.summarize(tmp_path, source_commit, run_id)

    assert result["result"] == "FAIL"
    assert result["claim"] == "NONE"
    assert expected_error in result["errors"]


def test_main_writes_only_part_3_summary(tmp_path: Path) -> None:
    write_valid_evidence(tmp_path)

    exit_code = MODULE.main(["summarize", str(tmp_path), "a" * 40, "123"])

    assert exit_code == 0
    assert (tmp_path / "part-3-summary.json").is_file()
    assert not (tmp_path / "part-2-summary.json").exists()


def test_main_preserves_failure_evidence_and_returns_nonzero(tmp_path: Path) -> None:
    write_valid_evidence(tmp_path)
    write_json(tmp_path / "teardown.json", {"result": "FAIL"})

    exit_code = MODULE.main(["summarize", str(tmp_path), "a" * 40, "123"])
    summary = json.loads((tmp_path / "part-3-summary.json").read_text(encoding="utf-8"))

    assert exit_code == 1
    assert summary["result"] == "FAIL"
    assert summary["claim"] == "NONE"
    assert (tmp_path / "evidence-manifest.sha256").is_file()


def test_manifest_is_deterministic_and_excludes_raw_terraform_material(tmp_path: Path) -> None:
    (tmp_path / "part-3-summary.json").write_text("{}", encoding="utf-8")
    (tmp_path / "z-last.json").write_text("{}", encoding="utf-8")
    (tmp_path / "a-first.json").write_text("{}", encoding="utf-8")
    (tmp_path / "apply.tfplan").write_text("private", encoding="utf-8")
    (tmp_path / "terraform-apply-plan.json").write_text("private", encoding="utf-8")
    (tmp_path / "terraform-outputs.json").write_text("private", encoding="utf-8")

    MODULE.write_manifest(tmp_path)

    manifest = (tmp_path / "evidence-manifest.sha256").read_text(encoding="utf-8")
    manifested_names = [line.split("  ", maxsplit=1)[1] for line in manifest.splitlines()]
    assert manifested_names == sorted(manifested_names)
    assert "part-3-summary.json" in manifest
    assert "apply.tfplan" not in manifest
    assert "terraform-apply-plan.json" not in manifest
    assert "terraform-outputs.json" not in manifest
