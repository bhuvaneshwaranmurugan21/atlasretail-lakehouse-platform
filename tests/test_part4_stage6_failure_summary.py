"""Failure finality and destroy-plan tamper checks for Stage 6."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_finalizer_writes_structured_failure_when_runtime_and_checkpoint_are_absent(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    output = evidence / "final-summary.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/finalize_part4_evidence.py"),
            "--evidence-directory",
            str(evidence),
            "--source-commit",
            "a" * 40,
            "--run-id",
            "123",
            "--run-attempt",
            "1",
            "--budget-ceiling-usd",
            "5",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 1
    summary = json.loads(output.read_text(encoding="utf-8"))
    assert summary["result"] == "FAIL"
    assert summary["claim_level"] == "UNCLAIMED"
    assert summary["aws_execution"] is False
    assert summary["production_claim"] is False
    assert summary["errors"]
