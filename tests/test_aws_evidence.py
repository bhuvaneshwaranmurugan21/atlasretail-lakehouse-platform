from atlasretail.aws_evidence import validate_aws_lab_evidence
from atlasretail.model import digest


def valid_bundle() -> dict[str, object]:
    payload: dict[str, object] = {
        "project": "atlasretail-lakehouse-platform",
        "claim_level": "AWS_LAB_VERIFIED",
        "production_claim": False,
        "result": "PASS",
        "region": "ap-south-1",
        "run_id": "ar-20260814-001",
        "commit_sha": "0123456789abcdef",
        "resources": {
            "landing_bucket": "atlas-redacted-landing",
            "lake_bucket": "atlas-redacted-lake",
            "glue_database": "atlasretail_lab",
            "run_table": "atlasretail-lab-runs",
            "active_pointer_table": "atlasretail-lab-pointer",
            "cloudwatch_log_group": "/aws/atlasretail/redacted",
        },
        "failure_tests": [
            "conflicting_replay",
            "schema_break",
            "processor_crash",
            "stale_publication",
            "isolated_backfill",
        ],
        "metrics": {
            "records_processed": 1000,
            "runtime_seconds": 35.2,
            "athena_bytes_scanned": 4096,
            "cost_usd": 0.72,
        },
        "teardown": {"destroyed": True, "verified_at": "2026-08-14T12:00:00Z"},
    }
    payload["evidence_digest"] = digest(payload)
    return payload


def test_complete_aws_evidence_contract_passes() -> None:
    assert validate_aws_lab_evidence(valid_bundle()) == ()


def test_evidence_contract_fails_closed() -> None:
    payload = valid_bundle()
    payload["resources"] = {}
    payload["metrics"] = {"cost_usd": -1}
    errors = validate_aws_lab_evidence(payload)
    assert any("resources missing" in error for error in errors)
    assert any("records_processed" in error for error in errors)
    assert any("cost_usd" in error for error in errors)
    assert any("evidence_digest" in error for error in errors)

