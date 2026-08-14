"""Fail-closed contract for a bounded AtlasRetail AWS lab."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .model import digest

REQUIRED_RESOURCES = {
    "landing_bucket",
    "lake_bucket",
    "glue_database",
    "run_table",
    "active_pointer_table",
    "cloudwatch_log_group",
}
REQUIRED_FAILURES = {
    "conflicting_replay",
    "schema_break",
    "processor_crash",
    "stale_publication",
    "isolated_backfill",
}


def validate_aws_lab_evidence(payload: Mapping[str, object]) -> tuple[str, ...]:
    errors: list[str] = []
    expected = {
        "project": "atlasretail-lakehouse-platform",
        "claim_level": "AWS_LAB_VERIFIED",
        "result": "PASS",
        "region": "ap-south-1",
        "production_claim": False,
    }
    errors.extend(f"{key} must equal {value}" for key, value in expected.items() if payload.get(key) != value)
    for field in ("run_id", "commit_sha"):
        if not isinstance(payload.get(field), str) or not str(payload[field]).strip():
            errors.append(f"{field} is required")

    resources = payload.get("resources")
    resource_map = resources if isinstance(resources, Mapping) else {}
    missing_resources = sorted(
        key for key in REQUIRED_RESOURCES if not isinstance(resource_map.get(key), str) or not resource_map[key]
    )
    if missing_resources:
        errors.append(f"resources missing values: {', '.join(missing_resources)}")

    failures = payload.get("failure_tests")
    observed = (
        {item for item in failures if isinstance(item, str)}
        if isinstance(failures, Sequence) and not isinstance(failures, (str, bytes))
        else set()
    )
    missing_failures = sorted(REQUIRED_FAILURES - observed)
    if missing_failures:
        errors.append(f"failure tests missing: {', '.join(missing_failures)}")

    metrics = payload.get("metrics")
    metric_map = metrics if isinstance(metrics, Mapping) else {}
    for field in ("records_processed", "runtime_seconds", "athena_bytes_scanned"):
        value = metric_map.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            errors.append(f"metrics.{field} must be positive")
    cost = metric_map.get("cost_usd")
    if not isinstance(cost, (int, float)) or isinstance(cost, bool) or cost < 0:
        errors.append("metrics.cost_usd must be a non-negative measured value")

    teardown = payload.get("teardown")
    teardown_map = teardown if isinstance(teardown, Mapping) else {}
    if teardown_map.get("destroyed") is not True or not teardown_map.get("verified_at"):
        errors.append("verified teardown is required")
    unsigned = {key: value for key, value in payload.items() if key != "evidence_digest"}
    if payload.get("evidence_digest") != digest(unsigned):
        errors.append("evidence_digest does not match canonical payload")
    return tuple(errors)

