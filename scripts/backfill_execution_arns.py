"""Recover exact Step Functions execution identities for diagnostic evidence collection."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

KINDS = ("success", "replay", "conflict", "failure", "recovery", "tamper", "temporal", "financial")


def backfill(source: Path, output: Path, run_id: str) -> int:
    payload: dict[str, Any] = json.loads(source.read_text(encoding="utf-8"))
    executions = payload.get("executions", [])
    if not isinstance(executions, list):
        raise ValueError("Step Functions execution inventory is invalid")
    if not re.fullmatch(r"[0-9]+", run_id):
        raise ValueError("run ID must be numeric")

    output.mkdir(parents=True, exist_ok=True)
    written = 0
    for kind in KINDS:
        expected_name = f"{kind}-{run_id}"
        matches = [row for row in executions if row.get("name") == expected_name]
        if len(matches) > 1:
            raise ValueError(f"duplicate execution identity: {expected_name}")
        if not matches:
            continue
        arn = str(matches[0].get("executionArn", ""))
        if not re.fullmatch(r"arn:aws:states:[a-z0-9-]+:[0-9]{12}:execution:[^:]+:[^:]+", arn):
            raise ValueError(f"invalid execution ARN: {expected_name}")
        target = output / f"{kind}-execution-arn.txt"
        if target.exists() and target.read_text(encoding="utf-8").strip() != arn:
            raise ValueError(f"execution ARN conflicts with existing evidence: {expected_name}")
        target.write_text(arn, encoding="utf-8")
        written += 1
    return written


def main(arguments: list[str]) -> int:
    if len(arguments) != 4:
        print(
            "usage: backfill_execution_arns.py EXECUTIONS_JSON OUTPUT_DIRECTORY RUN_ID",
            file=sys.stderr,
        )
        return 2
    try:
        backfill(Path(arguments[1]), Path(arguments[2]), arguments[3])
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
