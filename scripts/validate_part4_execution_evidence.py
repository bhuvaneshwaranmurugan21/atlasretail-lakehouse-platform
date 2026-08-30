#!/usr/bin/env python3
"""Validate and persist the non-final Part 4 execution checkpoint."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from atlasretail.part4_evidence import (
    EvidenceContext,
    EvidenceError,
    build_execution_manifest,
    canonical_manifest_sha256,
    validate_execution,
)

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
        result = validate_execution(context)
    except (EvidenceError, OSError, ValueError, KeyError, TypeError) as error:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "proof": "part4-execution-checkpoint",
                    "result": "FAIL",
                    "claim_level": "UNCLAIMED",
                    "execution_state": "AWS_EXECUTION_VALIDATED_PENDING_TEARDOWN",
                    "aws_execution": True,
                    "teardown_complete": False,
                    "provenance": {},
                    "domains": {},
                    "metered_usage": {},
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
        print(f"Part 4 execution evidence rejected: {error}", file=sys.stderr)
        return 1
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_execution_manifest(arguments.evidence_directory)
    if canonical_manifest_sha256(manifest) != result["evidence_manifest_sha256"]:
        print("Part 4 execution manifest changed during validation", file=sys.stderr)
        return 1
    (arguments.evidence_directory / "execution-evidence-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    arguments.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
