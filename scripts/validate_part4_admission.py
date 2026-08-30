#!/usr/bin/env python3
"""Independently verify a downloaded Part 4 admission receipt and source tree."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from atlasretail.part4_admission import (
    AdmissionContext,
    AdmissionError,
    load_receipt,
    verify_admission_receipt,
)

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--source-directory", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--workflow-name", required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--repository-owner", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--checked-out-commit", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--order-count", required=True)
    parser.add_argument("--budget-ceiling-usd", required=True)
    parser.add_argument("--confirm-execute", required=True)
    parser.add_argument("--confirm-destroy", required=True)
    return parser.parse_args()


def context(arguments: argparse.Namespace) -> AdmissionContext:
    return AdmissionContext(
        repository=arguments.repository,
        workflow_name=arguments.workflow_name,
        event=arguments.event,
        ref=arguments.ref,
        actor=arguments.actor,
        repository_owner=arguments.repository_owner,
        source_commit=arguments.source_commit,
        checked_out_commit=arguments.checked_out_commit,
        run_id=arguments.run_id,
        run_attempt=arguments.run_attempt,
        order_count=arguments.order_count,
        budget_ceiling_usd=arguments.budget_ceiling_usd,
        confirm_execute=arguments.confirm_execute,
        confirm_destroy=arguments.confirm_destroy,
    )


def main() -> int:
    arguments = parse_args()
    try:
        receipt = load_receipt(arguments.receipt)
        verify_admission_receipt(
            receipt,
            repo_root=arguments.repo_root.resolve(),
            source_directory=arguments.source_directory.resolve(),
            context=context(arguments),
        )
    except AdmissionError as error:
        print(f"Part 4 admission receipt rejected: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
