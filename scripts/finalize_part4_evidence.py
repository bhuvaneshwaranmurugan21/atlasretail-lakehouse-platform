#!/usr/bin/env python3
"""Finalize Part 4 evidence only after clean teardown and lease finality."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from atlasretail.part4_evidence import EvidenceContext, EvidenceError, finalize_evidence

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-directory", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--budget-ceiling-usd", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    context = EvidenceContext(
        root=arguments.evidence_directory,
        repo_root=ROOT,
        source_commit=arguments.source_commit,
        run_id=arguments.run_id,
        run_attempt=arguments.run_attempt,
        budget_ceiling_usd=arguments.budget_ceiling_usd,
    )
    try:
        result = finalize_evidence(context)
    except (EvidenceError, OSError, ValueError, KeyError, TypeError) as error:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "proof": "part4-final-evidence",
                    "result": "FAIL",
                    "claim_level": "UNCLAIMED",
                    "aws_execution": (
                        arguments.evidence_directory / "execution-checkpoint.json"
                    ).exists(),
                    "production_claim": False,
                    "provenance": {},
                    "domains": {},
                    "checkpoint_sha256": "0" * 64,
                    "evidence_manifest_sha256": "0" * 64,
                    "actual_billed_cost_claim": "UNCLAIMED",
                    "errors": [str(error)],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"Part 4 final evidence rejected: {error}", file=sys.stderr)
        return 1
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
