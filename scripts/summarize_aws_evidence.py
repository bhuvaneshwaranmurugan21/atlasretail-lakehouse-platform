#!/usr/bin/env python3
"""Reject the retired pre-teardown AWS evidence summary path."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(arguments: list[str]) -> int:
    if len(arguments) < 2:
        print("usage: summarize_aws_evidence.py EVIDENCE_DIRECTORY", file=sys.stderr)
        return 2
    root = Path(arguments[1])
    source_commit = arguments[2] if len(arguments) > 2 else "unknown"
    root.mkdir(parents=True, exist_ok=True)
    reason = (
        "Pre-teardown summarization is retired; validate the execution checkpoint "
        "and finalize only after teardown and lease verification."
    )
    result = {
        "result": "FAIL",
        "claim_level": "UNCLAIMED",
        "production_claim": False,
        "source_commit": source_commit,
        "reason": reason,
    }
    (root / "summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(reason, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
