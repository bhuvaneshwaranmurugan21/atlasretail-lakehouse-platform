from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

EVIDENCE = Path(__file__).parents[1] / "evidence" / "aws" / "bounded" / "33167646509"
SUMMARY_FILES = {
    "failure-isolation.json",
    "plan-summary.json",
    "summary.json",
    "teardown-summary.json",
}


def load(name: str) -> dict[str, Any]:
    value = json.loads((EVIDENCE / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_current_bounded_evidence_is_attributed_sanitized_and_digest_verified() -> None:
    manifest = load("manifest.json")

    assert manifest["result"] == "PASS"
    assert manifest["run_id"] == 33167646509
    assert manifest["run_number"] == 13
    assert manifest["source_commit"] == "0c2df3b21c1ac09f76d682e9077dcc4467318530"
    assert manifest["aws_account_id"] == "857229544428"
    assert manifest["aws_region"] == "ap-southeast-2"
    assert manifest["production_claim"] is False
    assert manifest["artifact"] == {
        "created_at": "2026-08-28T12:00:06Z",
        "id": 9684904182,
        "name": "atlasretail-aws-evidence-33167646509",
        "sha256": "88522723ba62815d10792fcfe855038b7b3303530029ece43ac6ec23d6fdd62f",
        "size_bytes": 1623304,
    }
    assert manifest["sanitization"] == {
        "caller_identity": "EXCLUDED",
        "live_resource_identifiers": "EXCLUDED",
        "raw_cloudwatch_events": "EXCLUDED",
        "raw_execution_histories": "EXCLUDED",
    }
    assert set(manifest["committed_summaries"]) == SUMMARY_FILES
    assert {path.name for path in EVIDENCE.iterdir()} == SUMMARY_FILES | {"manifest.json"}

    for name, expected_digest in manifest["committed_summaries"].items():
        digest = hashlib.sha256((EVIDENCE / name).read_bytes()).hexdigest()
        assert digest == expected_digest


def test_current_bounded_evidence_proves_the_managed_path_without_production_claims() -> None:
    summary = load("summary.json")
    failures = load("failure-isolation.json")
    plans = load("plan-summary.json")
    teardown = load("teardown-summary.json")

    assert summary["result"] == "PASS"
    assert summary["claim_level"] == "AWS_VERIFIED"
    assert summary["production_claim"] is False
    assert summary["source_commit"] == "0c2df3b21c1ac09f76d682e9077dcc4467318530"
    assert all(check["passed"] for check in summary["checks"]["executions"].values())
    assert summary["checks"]["failure_did_not_move_pointer"] is True
    assert summary["checks"]["stale_publisher_rejected"] is True
    assert summary["checks"]["serving_generation_resolved_once"] is True
    assert summary["checks"]["six_table_serving_query_completed"] is True
    assert summary["checks"]["athena_result_matches_expected"] is True
    assert summary["business_result"] == {
        "actual": {"gross_cents": 4595276, "orders": 500},
        "expected": {"gross_cents": 4595276, "orders": 500},
        "result": "PASS",
    }
    assert summary["checks"]["cloudwatch_exports"] == {
        "glue-cloudwatch-events.json": {"event_count": 28921, "passed": True},
        "lambda-cloudwatch-events.json": {"event_count": 84, "passed": True},
        "states-cloudwatch-events.json": {"event_count": 187, "passed": True},
    }
    assert summary["metered_usage"] == {
        "athena_bytes_scanned": 2192,
        "athena_queries": 2,
        "glue_dpu_seconds": 1562.0,
        "glue_job_runs": 6,
        "workflow_to_evidence_seconds": 1325,
    }
    assert summary["immediate_cost_estimate_usd"]["partial_total"] == 0.191016
    assert "settle later" in summary["immediate_cost_estimate_usd"]["scope"]

    assert failures["result"] == "PASS"
    assert failures["glue_job_runs"] == {"expected_failed": 4, "succeeded": 2, "total": 6}
    assert set(failures["observed_failure_markers"]) == {
        "INJECTED_FAILURE",
        "QUALITY_GATE:AMBIGUOUS_DIMENSION",
        "QUALITY_GATE:OBJECT_IDENTITY",
        "QUALITY_GATE:ORDER_TOTAL",
    }
    assert all(failures["checks"].values())

    assert plans["result"] == "PASS"
    assert plans["apply"]["resource_count"] == 40
    assert plans["apply"]["result"] == "PASS"
    assert plans["destroy"]["resource_count"] == 40
    assert plans["destroy"]["result"] == "PASS"

    assert teardown["result"] == "PASS"
    assert teardown["teardown_check_count"] == 20
    assert teardown["checks"] == {
        "all_teardown_checks_passed": True,
        "exact_resource_absence_check_count": 17,
        "terraform_state_empty": True,
        "unexpected_run_tagged_resources": [],
    }
    assert teardown["kms_key_disposition"] == {
        "deletion_date_verified": True,
        "status": "PENDING_DELETION",
    }
