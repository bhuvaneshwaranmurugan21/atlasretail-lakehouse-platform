"""Tests for the bounded AWS evidence summary contract."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "summarize_aws_evidence.py"


def write(path: Path, name: str, value: object) -> None:
    (path / name).write_text(json.dumps(value), encoding="utf-8")


def complete_evidence(path: Path) -> None:
    write(
        path,
        "stepfunctions-executions.json",
        {
            "executions": [
                {"name": "success-1", "status": "SUCCEEDED"},
                {"name": "replay-1", "status": "SUCCEEDED"},
                {"name": "conflict-1", "status": "FAILED"},
                {"name": "failure-1", "status": "FAILED"},
                {"name": "recovery-1", "status": "SUCCEEDED"},
                {"name": "tamper-1", "status": "FAILED"},
                {"name": "temporal-1", "status": "FAILED"},
                {"name": "financial-1", "status": "FAILED"},
            ]
        },
    )
    write(path, "glue-job-runs.json", {"JobRuns": [{"DPUSeconds": 120.0}]})
    write(
        path,
        "athena-orders.json",
        {"QueryExecution": {"Statistics": {"DataScannedInBytes": 4096}}},
    )
    write(
        path,
        "athena-six-table-serving.json",
        {"QueryExecution": {"Statistics": {"DataScannedInBytes": 8192}}},
    )
    write(path, "athena-validation.json", {"result": "PASS"})
    write(
        path,
        "serving-resolution.json",
        {"status": "RESOLVED", "generation_id": "g-recovery-1", "pointer_version": 2},
    )
    write(
        path,
        "athena-six-table-serving-results.json",
        {
            "ResultSet": {
                "Rows": [
                    {
                        "Data": [
                            {"VarCharValue": name}
                            for name in (
                                "orders",
                                "order_lines",
                                "payments",
                                "returns",
                                "inventory_movements",
                                "products",
                            )
                        ]
                    },
                    {"Data": [{"VarCharValue": "1"}] * 6},
                ]
            }
        },
    )
    (path / "stale-publisher").mkdir()
    write(path / "stale-publisher", "summary.json", {"result": "PASS"})
    for name in (
        "glue-cloudwatch-events.json",
        "states-cloudwatch-events.json",
        "lambda-cloudwatch-events.json",
    ):
        write(path, name, {"events": []})
    pointer = {"Item": {"active_generation": {"S": "g-success-1"}}}
    write(path, "pointer-before-failure.json", pointer)
    write(path, "pointer-after-failure.json", pointer)
    (path / "workflow-started-epoch.txt").write_text("100", encoding="utf-8")
    (path / "workflow-evidence-collected-epoch.txt").write_text("223", encoding="utf-8")


def run_summary(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(path), "a" * 40],
        check=False,
        capture_output=True,
        text=True,
    )


def test_complete_evidence_passes(tmp_path: Path) -> None:
    complete_evidence(tmp_path)

    completed = run_summary(tmp_path)
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))

    assert completed.returncode == 0
    assert summary["result"] == "PASS"
    assert summary["metered_usage"]["workflow_to_evidence_seconds"] == 123


def test_missing_cloudwatch_export_fails(tmp_path: Path) -> None:
    complete_evidence(tmp_path)
    (tmp_path / "glue-cloudwatch-events.json").unlink()

    completed = run_summary(tmp_path)
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))

    assert completed.returncode == 1
    assert summary["result"] == "FAIL"
    assert summary["checks"]["cloudwatch_exports"]["glue-cloudwatch-events.json"] is False
