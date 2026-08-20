"""Create a compact, honest summary from an AtlasRetail AWS evidence directory."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

root = Path(sys.argv[1])
source_commit = sys.argv[2]


def load(name: str) -> dict[str, Any]:
    path = root / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


execution_rows = load("stepfunctions-executions.json").get("executions", [])
statuses = {row["name"].split("-")[0]: row["status"] for row in execution_rows}
expected = {
    "success": "SUCCEEDED",
    "replay": "SUCCEEDED",
    "conflict": "FAILED",
    "failure": "FAILED",
    "recovery": "SUCCEEDED",
    "tamper": "FAILED",
    "temporal": "FAILED",
    "financial": "FAILED",
}
execution_checks = {
    name: {"expected": status, "actual": statuses.get(name), "passed": statuses.get(name) == status}
    for name, status in expected.items()
}

glue_runs = load("glue-job-runs.json").get("JobRuns", [])
dpu_seconds = 0.0
for run in glue_runs:
    if "DPUSeconds" in run:
        dpu_seconds += float(run["DPUSeconds"])
    else:
        dpu_seconds += float(run.get("ExecutionTime", 0)) * float(run.get("NumberOfWorkers", 2))

athena_queries = [load("athena-orders.json"), load("athena-six-table-serving.json")]
athena_scans = [
    int(query.get("QueryExecution", {}).get("Statistics", {}).get("DataScannedInBytes", 0))
    for query in athena_queries
]
athena_bytes = sum(athena_scans)

# Immediate metered estimate, not an invoice. Reference rates are in cost-model.md.
glue_estimate_usd = dpu_seconds / 3600 * 0.44
athena_billable_bytes = sum(max(value, 10 * 1024 * 1024) for value in athena_scans if value)
athena_estimate_usd = athena_billable_bytes / 1_000_000_000_000 * 5.0

pointer_unchanged = False
before = root / "pointer-before-failure.json"
after = root / "pointer-after-failure.json"
if before.exists() and after.exists():
    pointer_unchanged = before.read_bytes() == after.read_bytes()

athena_validation = load("athena-validation.json")
athena_matches = athena_validation.get("result") == "PASS"
serving_resolution = load("serving-resolution.json")
serving_resolved = (
    serving_resolution.get("status") == "RESOLVED"
    and bool(serving_resolution.get("generation_id"))
    and int(serving_resolution.get("pointer_version", 0)) > 0
)
serving_rows = load("athena-six-table-serving-results.json").get("ResultSet", {}).get("Rows", [])
serving_headers = []
if serving_rows:
    serving_headers = [
        cell.get("VarCharValue")
        for cell in serving_rows[0].get("Data", [])
        if isinstance(cell, dict)
    ]
six_table_serving = (
    serving_headers
    == [
        "orders",
        "order_lines",
        "payments",
        "returns",
        "inventory_movements",
        "products",
    ]
    and len(serving_rows) == 2
)
stale_publisher_rejected = load("stale-publisher/summary.json").get("result") == "PASS"
cloudwatch_files = (
    "glue-cloudwatch-events.json",
    "states-cloudwatch-events.json",
    "lambda-cloudwatch-events.json",
)
cloudwatch_exports = {name: isinstance(load(name).get("events"), list) for name in cloudwatch_files}
cloudwatch_evidence_complete = all(cloudwatch_exports.values())
checks_passed = (
    all(value["passed"] for value in execution_checks.values())
    and pointer_unchanged
    and athena_matches
    and serving_resolved
    and six_table_serving
    and stale_publisher_rejected
    and cloudwatch_evidence_complete
)

elapsed_seconds = 0
started = root / "workflow-started-epoch.txt"
collected = root / "workflow-evidence-collected-epoch.txt"
if started.exists() and collected.exists():
    elapsed_seconds = max(0, int(collected.read_text()) - int(started.read_text()))
summary = {
    "project": "atlasretail-lakehouse-platform",
    "claim_level": "AWS_VERIFIED" if checks_passed else "AWS_EXECUTION_INCOMPLETE",
    "production_claim": False,
    "source_commit": source_commit,
    "result": "PASS" if checks_passed else "FAIL",
    "checks": {
        "executions": execution_checks,
        "failure_did_not_move_pointer": pointer_unchanged,
        "athena_result_matches_expected": athena_matches,
        "serving_generation_resolved_once": serving_resolved,
        "six_table_serving_query_completed": six_table_serving,
        "stale_publisher_rejected": stale_publisher_rejected,
        "cloudwatch_exports": cloudwatch_exports,
    },
    "business_result": athena_validation,
    "metered_usage": {
        "glue_job_runs": len(glue_runs),
        "glue_dpu_seconds": round(dpu_seconds, 3),
        "athena_bytes_scanned": athena_bytes,
        "athena_queries": sum(1 for value in athena_scans if value),
        "workflow_to_evidence_seconds": elapsed_seconds,
    },
    "immediate_cost_estimate_usd": {
        "glue": round(glue_estimate_usd, 6),
        "athena": round(athena_estimate_usd, 6),
        "partial_total": round(glue_estimate_usd + athena_estimate_usd, 6),
        "scope": (
            "Glue compute and bounded Athena queries only; billing data and minor service charges "
            "settle later."
        ),
    },
}
(root / "summary.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
raise SystemExit(0 if summary["result"] == "PASS" else 1)
