from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1] / "evidence" / "aws"
BOUNDED = ROOT / "bounded" / "33329861907"
RECOVERY = ROOT / "recovery" / "33328391707"
PREFLIGHT = ROOT / "preflight" / "33331233341"


def load(directory: Path, name: str) -> dict[str, Any]:
    value = json.loads((directory / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def assert_committed_digests(directory: Path) -> None:
    manifest = load(directory, "manifest.json")
    expected = manifest["committed_summaries"]
    assert {path.name for path in directory.iterdir()} == set(expected) | {"manifest.json"}
    for name, expected_digest in expected.items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == expected_digest


def test_stage6_bounded_evidence_is_attributed_sanitized_and_digest_verified() -> None:
    manifest = load(BOUNDED, "manifest.json")

    assert manifest["result"] == "PASS"
    assert manifest["run_id"] == 33329861907
    assert manifest["run_attempt"] == 1
    assert manifest["run_number"] == 18
    assert manifest["source_commit"] == "08559b0f48708080335282c6d59faa3826635d67"
    assert manifest["aws_account_id"] == "857229544428"
    assert manifest["aws_region"] == "ap-southeast-2"
    assert manifest["production_claim"] is False
    assert manifest["artifact"] == {
        "created_at": "2026-08-30T19:33:05Z",
        "id": 9737679077,
        "name": "atlasretail-aws-evidence-33329861907",
        "sha256": "f9971511d6de33c11d73c7fb64df5fe30c9a1ff7b2e4b802ae6a36b707fd1399",
        "size_bytes": 1710288,
    }
    assert manifest["prerequisite_artifacts"] == {
        "glue_capability_probe": {
            "artifact_id": 9737259594,
            "artifact_sha256": ("64b8031a6d96d48c34c6c37d671728dc17a74b9e445324cee8a4eb6f23ae79dd"),
            "run_id": 33329607444,
        },
        "plan_only_proof": {
            "artifact_id": 9737293923,
            "artifact_sha256": ("2ed65448d318867ba6132f2f913372444f14df6309c0cc19a3efeca49003a508"),
            "run_id": 33329689861,
        },
        "read_only_preflight": {
            "artifact_id": 9736958383,
            "artifact_sha256": ("9a6fafd2801bde102341e713a1a822e68b45fa1f86201be17d8e699d2f889806"),
            "run_id": 33328532420,
        },
    }
    assert all(value == "EXCLUDED" for value in manifest["sanitization"].values())
    assert_committed_digests(BOUNDED)


def test_stage6_bounded_evidence_proves_all_contract_domains_and_finality() -> None:
    summary = load(BOUNDED, "summary.json")
    failures = load(BOUNDED, "failure-isolation.json")
    plans = load(BOUNDED, "plan-summary.json")
    teardown = load(BOUNDED, "teardown-summary.json")

    assert summary["result"] == "PASS"
    assert summary["claim_level"] == "AWS_VERIFIED"
    assert summary["aws_execution"] is True
    assert summary["production_claim"] is False
    assert summary["actual_billed_cost_claim"] == "UNCLAIMED"
    assert summary["source_commit"] == "08559b0f48708080335282c6d59faa3826635d67"
    assert summary["checks"]["contract_domain_count"] == 20
    assert summary["checks"]["all_contract_domains_passed"] is True
    assert summary["checks"]["finalized_after_lease_release"] is True
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
        "glue-cloudwatch-events.json": {"event_count": 29538, "passed": True},
        "lambda-cloudwatch-events.json": {"event_count": 90, "passed": True},
        "states-cloudwatch-events.json": {"event_count": 184, "passed": True},
    }
    assert summary["metered_usage"] == {
        "athena_bytes_scanned": 2192,
        "athena_queries": 2,
        "execution_to_finality_seconds": 1646.816,
        "glue_dpu_seconds": 1323.0,
        "glue_job_runs": 6,
    }
    assert summary["immediate_cost_estimate_usd"]["partial_total"] == 0.161805
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
    assert plans["apply"]["exact_envelope"] is True
    assert plans["apply"]["resource_count"] == 40
    assert plans["destroy"]["exact_envelope"] is True
    assert plans["destroy"]["resource_count"] == 40
    assert plans["destroy"]["partial_destroy_recovery"] is False

    assert teardown["result"] == "PASS"
    assert teardown["teardown_check_count"] == 20
    assert teardown["checks"] == {
        "all_teardown_checks_passed": True,
        "exact_resource_absence_check_count": 17,
        "terraform_state_empty": True,
        "unexpected_run_tagged_resources": [],
    }
    assert teardown["kms_key_disposition"] == {
        "alias_absent": True,
        "deletion_date_verified": True,
        "status": "PENDING_DELETION",
    }
    assert teardown["lease_release"]["result"] == "PASS"
    assert teardown["lease_release"]["lease_absent"] is True
    assert teardown["lease_release"]["consistent_read"] is True


def test_stage6_recovery_evidence_is_cleanup_only_and_exactly_attributed() -> None:
    manifest = load(RECOVERY, "manifest.json")
    summary = load(RECOVERY, "summary.json")
    plan = load(RECOVERY, "plan-summary.json")
    teardown = load(RECOVERY, "teardown-summary.json")
    lease = load(RECOVERY, "lease-release-summary.json")

    assert manifest["result"] == "PASS"
    assert manifest["run_id"] == 33328391707
    assert manifest["failed_run_id"] == 33326519783
    assert manifest["failed_source_commit"] == "d074175c0e1b7937400e488dd2e8265d900b8841"
    assert manifest["recovery_control_commit"] == "08559b0f48708080335282c6d59faa3826635d67"
    assert manifest["workload_execution"] is False
    assert summary["claim_level"] == "AWS_VERIFIED"
    assert summary["cleanup_only"] is True
    assert summary["workload_execution"] is False
    assert summary["teardown_complete"] is True
    assert summary["lease_released"] is True
    assert plan == {
        "errors": [],
        "exact_envelope": False,
        "mode": "destroy",
        "partial_destroy_recovery": True,
        "resource_count": 40,
        "result": "PASS",
    }
    assert teardown["check_count"] == 20
    assert teardown["all_checks_deleted"] is True
    assert teardown["terraform_state_empty"] is True
    assert teardown["unexpected_run_tagged_resources"] == []
    assert lease["result"] == "PASS"
    assert lease["expected_state"] == "RECOVERY_BOUND"
    assert lease["conditional_delete_exit_code"] == 0
    assert lease["lease_absent"] is True
    assert lease["consistent_read"] is True
    assert_committed_digests(RECOVERY)


def test_stage6_independent_post_teardown_preflight_proves_clean_state() -> None:
    manifest = load(PREFLIGHT, "manifest.json")
    summary = load(PREFLIGHT, "summary.json")

    assert manifest["result"] == "PASS"
    assert manifest["run_id"] == 33331233341
    assert manifest["source_commit"] == "08559b0f48708080335282c6d59faa3826635d67"
    assert manifest["artifact"]["sha256"] == (
        "82e3bfca64ae841d9aefda0467301eaf6b4420547fb5795051d248c22e4bd904"
    )
    assert summary["claim_level"] == "AWS_VERIFIED"
    assert summary["account_lease_absent"] is True
    assert summary["terraform_state_resources"] == []
    assert summary["unexpected_resources"] == []
    assert summary["kms_inspection_error_count"] == 0
    assert summary["pending_deletion_kms_alias_count"] == 0
    assert summary["pending_deletion_kms_key_count"] == 13
    assert_committed_digests(PREFLIGHT)
