#!/usr/bin/env python3
"""Validate exact current-source prerequisites for Part 4 managed execution."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from atlasretail.part4_stage6_prerequisites import (
    PrerequisiteContext,
    build_prerequisite_receipt,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-dir", type=Path, required=True)
    parser.add_argument("--glue-probe-dir", type=Path, required=True)
    parser.add_argument("--plan-dir", type=Path, required=True)
    parser.add_argument("--preflight-run-id", required=True)
    parser.add_argument("--glue-probe-run-id", required=True)
    parser.add_argument("--plan-run-id", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    receipt = build_prerequisite_receipt(
        preflight_dir=arguments.preflight_dir,
        glue_probe_dir=arguments.glue_probe_dir,
        plan_dir=arguments.plan_dir,
        context=PrerequisiteContext(
            source_commit=arguments.source_commit,
            repository=arguments.repository,
            ref=arguments.ref,
            preflight_run_id=arguments.preflight_run_id,
            glue_probe_run_id=arguments.glue_probe_run_id,
            plan_run_id=arguments.plan_run_id,
        ),
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
