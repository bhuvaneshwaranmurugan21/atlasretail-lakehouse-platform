from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1] / "evidence" / "aws"
DEPLOYMENT = ROOT / "deployment" / "33255708391"
PREFLIGHT = ROOT / "preflight" / "33257068545"
DEPLOYMENT_SUMMARIES = {
    "admission-verification.json",
    "budget-summary.json",
    "deployment-summary.json",
    "part-3-summary.json",
    "plan-summary.json",
    "teardown-summary.json",
}
PREFLIGHT_SUMMARIES = {"summary.json"}


def load(directory: Path, name: str) -> dict[str, Any]:
    value = json.loads((directory / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def assert_manifest(directory: Path, expected_files: set[str]) -> dict[str, Any]:
    manifest = load(directory, "manifest.json")
    assert set(manifest["committed_summaries"]) == expected_files
    assert {path.name for path in directory.iterdir()} == expected_files | {"manifest.json"}
    for name, expected_digest in manifest["committed_summaries"].items():
        digest = hashlib.sha256((directory / name).read_bytes()).hexdigest()
        assert digest == expected_digest
    return manifest


def test_controlled_deployment_is_source_bound_sanitized_and_digest_verified() -> None:
    manifest = assert_manifest(DEPLOYMENT, DEPLOYMENT_SUMMARIES)
    assert manifest["result"] == "PASS"
    assert manifest["run_id"] == 33255708391
    assert manifest["run_number"] == 5
    assert manifest["source_commit"] == "c4f2a24d89c1770fe4eb020174e047c67e010e3b"
    assert manifest["aws_account_id"] == "857229544428"
    assert manifest["aws_region"] == "ap-southeast-2"
    assert manifest["production_claim"] is False
    assert manifest["artifact"]["id"] == 9715810551
    assert manifest["artifact"]["sha256"] == (
        "e6cee2ddf8eaf35ebefbb7e8d5a6656032b4e5a7fb4185d2240ea0c00e0461d6"
    )
    assert all(value == "EXCLUDED" for value in manifest["sanitization"].values())


def test_controlled_deployment_proves_zero_workload_and_exact_teardown() -> None:
    admission = load(DEPLOYMENT, "admission-verification.json")
    summary = load(DEPLOYMENT, "part-3-summary.json")
    deployment = load(DEPLOYMENT, "deployment-summary.json")
    plans = load(DEPLOYMENT, "plan-summary.json")
    teardown = load(DEPLOYMENT, "teardown-summary.json")
    budget = load(DEPLOYMENT, "budget-summary.json")

    assert admission["result"] == "PASS"
    assert admission["source_commit"] == summary["source_commit"]
    assert admission["prerequisite_runs"] == {
        "glue_capability_probe": "33255546906",
        "plan_only_proof": "33255077636",
        "read_only_preflight": "33255362691",
    }
    assert summary["result"] == "PASS"
    assert summary["claim"] == "AWS_DEPLOYMENT_VERIFIED"
    assert summary["proof"] == "zero-workload-controlled-deployment"
    assert summary["zero_workload"] == "PASS"
    assert summary["terraform_managed_resource_count"] == 40
    assert summary["runtime_seconds"] == 351
    assert summary["active_residue"] == 0
    assert all(summary["checks"].values())
    assert deployment["result"] == "PASS"
    assert deployment["zero_workload"] == "PASS"
    assert all(deployment["checks"].values())
    assert plans["apply"]["resource_count"] == 40
    assert plans["destroy"]["resource_count"] == 40
    assert plans["saved_plans_only"] is True
    assert teardown["result"] == "PASS"
    assert teardown["checks"]["account_lease_released"] is True
    assert teardown["checks"]["terraform_state_empty"] is True
    assert teardown["checks"]["unexpected_run_tagged_resources"] == []
    assert teardown["kms_key_disposition"]["status"] == "PENDING_DELETION"
    assert budget["result"] == "PASS"
    assert budget["actual_billed_cost"] == "UNCLAIMED"


def test_independent_post_teardown_preflight_proves_clean_active_inventory() -> None:
    manifest = assert_manifest(PREFLIGHT, PREFLIGHT_SUMMARIES)
    summary = load(PREFLIGHT, "summary.json")

    assert manifest["result"] == "PASS"
    assert manifest["run_id"] == 33257068545
    assert manifest["run_number"] == 20
    assert manifest["source_commit"] == "c4f2a24d89c1770fe4eb020174e047c67e010e3b"
    assert manifest["aws_account_id"] == "857229544428"
    assert manifest["aws_region"] == "ap-southeast-2"
    assert manifest["artifact"]["id"] == 9716137502
    assert manifest["artifact"]["sha256"] == (
        "e522c6864261b2d24f5d166119f5f3b8ae3aabb6724a696dafa8c73003068ed4"
    )
    assert summary["result"] == "PASS"
    assert summary["claim_level"] == "AWS_VERIFIED"
    assert summary["checks"] == {
        "account_lease_absent": True,
        "kms_inspection_errors": [],
        "pending_deletion_kms_alias_count": 0,
        "pending_deletion_kms_key_count": 11,
        "terraform_state_resources": [],
        "unexpected_resources": [],
    }
