#!/usr/bin/env python3
"""Verify that the completed Stage 6 managed runtime remains byte-equivalent."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from atlasretail.part4_stage7_closure import ClosureError, build_runtime_receipt

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) == 2 else Path("part4-stage7-runtime.json")
    try:
        result = build_runtime_receipt(ROOT)
    except (ClosureError, OSError, ValueError) as error:
        print(f"Part 4 Stage 7 runtime verification rejected: {error}", file=sys.stderr)
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if result["result"] != "PASS":
        print("; ".join(result["errors"]), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
