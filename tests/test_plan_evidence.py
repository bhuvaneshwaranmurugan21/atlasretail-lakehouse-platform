from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

EVIDENCE = Path(__file__).parents[1] / "evidence" / "aws" / "plan" / "32929299555"
SUMMARY_FILES = {
    "account-plan-verification.json",
    "budget-verification.json",
    "iam-parity.json",
    "preflight-before.json",
    "terraform-plan-validation.json",
    "terraform-plan-inventory.json",
    "state-machine-validation.json",
    "preflight-after.json",
    "no-change-verification.json",
    "summary.json",
}


def load(name: str) -> dict[str, Any]:
    value = json.loads((EVIDENCE / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_plan_evidence_is_attributed_and_digest_verified() -> None:
    manifest = load("manifest.json")

    assert manifest["result"] == "PASS"
    assert manifest["run_id"] == 32929299555
    assert manifest["run_number"] == 9
    assert manifest["source_commit"] == "8d94d3726d2d1976d849c582316ed503a7ae7762"
    assert manifest["aws_account_id"] == "857229544428"
    assert manifest["aws_region"] == "ap-southeast-2"
    assert set(manifest["committed_summaries"]) == SUMMARY_FILES
    assert {path.name for path in EVIDENCE.iterdir()} == SUMMARY_FILES | {"manifest.json"}

    for name, expected_digest in manifest["committed_summaries"].items():
        digest = hashlib.sha256((EVIDENCE / name).read_bytes()).hexdigest()
        assert digest == expected_digest


def test_plan_evidence_proves_the_required_gate() -> None:
    manifest = load("manifest.json")
    account_plan = load("account-plan-verification.json")
    budget = load("budget-verification.json")
    iam = load("iam-parity.json")
    before = load("preflight-before.json")
    plan = load("terraform-plan-validation.json")
    inventory = load("terraform-plan-inventory.json")
    state_machine = load("state-machine-validation.json")
    after = load("preflight-after.json")
    no_change = load("no-change-verification.json")
    summary = load("summary.json")

    assert account_plan["result"] == "PASS"
    assert account_plan["account_plan_api_available"] is False
    assert account_plan["account_plan_lookup_result"] == "NOT_FOUND"
    assert account_plan["credit_source"] == "organization-shared"
    assert account_plan["organization_shared_credit_usd"] == 120.0
    assert account_plan["errors"] == []
    assert account_plan["organization_credit_errors"] == []

    assert budget["result"] == "PASS"
    assert budget["budget_limit_usd"] == 20.0
    assert budget["current_spend_usd"] == 0.0
    assert budget["budget_headroom_usd"] == 20.0
    assert budget["planned_gross_cost_ceiling_usd"] == 5.0
    assert budget["notification_count"] == 3
    assert budget["errors"] == []

    assert iam["result"] == "PASS"
    assert iam["tracked_policy_matches_live"] is True
    assert iam["no_attached_managed_policies"] is True
    assert iam["errors"] == []

    empty_baseline = {
        "allowed_pending_deletion_kms_keys": [],
        "errors": [],
        "result": "PASS",
        "terraform_state_resources": [],
        "unexpected_resources": [],
    }
    assert before == empty_baseline
    assert after == empty_baseline

    assert plan["result"] == "PASS"
    assert plan["mode"] == "apply"
    assert plan["resource_count"] == 40
    assert plan["read_only_data_source_counts"] == {"aws_iam_policy_document": 6}
    assert plan["errors"] == []

    changes = inventory["resource_changes"]
    managed = [change for change in changes if change["mode"] == "managed"]
    data = [change for change in changes if change["mode"] == "data"]
    assert inventory["resource_change_count"] == 46
    assert len(managed) == 40
    assert len(data) == 6
    assert all(change["actions"] == ["create"] for change in managed)
    assert all(change["actions"] == ["read"] for change in data)
    assert inventory["raw_plan_sha256"] == manifest["ephemeral_plan_sha256"]["expanded_json"]

    assert state_machine == {"result": "OK", "diagnostics": [], "truncated": False}
    assert no_change["result"] == "PASS"
    assert no_change["persistent_inventory_unchanged"] is True
    assert no_change["errors"] == []

    assert summary["result"] == "PASS"
    assert summary["claim_level"] == "AWS_PLAN_VERIFIED"
    assert summary["source_commit"] == manifest["source_commit"]
    assert summary["github_run_id"] == str(manifest["run_id"])
    assert all(summary["checks"].values())
    assert summary["infrastructure_deployed"] is False
    assert summary["saved_plan_applied"] is False
    assert summary["planned_managed_resource_count"] == 40
    assert summary["warnings"] == []
