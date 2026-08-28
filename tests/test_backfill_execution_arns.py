from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "backfill_execution_arns.py"
SPEC = importlib.util.spec_from_file_location("backfill_execution_arns", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
backfill = MODULE.backfill


def write_inventory(path: Path, rows: list[dict[str, str]]) -> None:
    path.write_text(json.dumps({"executions": rows}), encoding="utf-8")


def test_backfills_only_exact_scenario_identities(tmp_path: Path) -> None:
    source = tmp_path / "executions.json"
    arn = "arn:aws:states:ap-southeast-2:857229544428:execution:pipeline:failure-42"
    write_inventory(
        source,
        [
            {"name": "failure-42", "executionArn": arn},
            {
                "name": "failure-41",
                "executionArn": (
                    "arn:aws:states:ap-southeast-2:857229544428:execution:pipeline:failure-41"
                ),
            },
        ],
    )

    assert backfill(source, tmp_path / "evidence", "42") == 1
    assert (tmp_path / "evidence" / "failure-execution-arn.txt").read_text() == arn


def test_rejects_conflicting_existing_identity(tmp_path: Path) -> None:
    source = tmp_path / "executions.json"
    write_inventory(
        source,
        [
            {
                "name": "recovery-42",
                "executionArn": (
                    "arn:aws:states:ap-southeast-2:857229544428:execution:pipeline:recovery-42"
                ),
            }
        ],
    )
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "recovery-execution-arn.txt").write_text("different", encoding="utf-8")

    with pytest.raises(ValueError, match="conflicts with existing evidence"):
        backfill(source, evidence, "42")
