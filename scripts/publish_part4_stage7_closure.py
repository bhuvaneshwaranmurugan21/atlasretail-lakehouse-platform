#!/usr/bin/env python3
"""Publish or verify sanitized Part 4 Stage 7 closure evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from atlasretail.part4_stage7_closure import (
    STAGE6_BOUNDED_RUN_ID,
    STAGE6_RECOVERY_RUN_ID,
    ClosureError,
    build_closure_receipt,
    publish_preflight_evidence,
    validate_closure_receipt,
)

ROOT = Path(__file__).resolve().parents[1]


def load_object(path: Path) -> dict[str, Any]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ClosureError(f"{path}: expected a JSON object")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_receipt(preflight_directory: Path, control_commit: str) -> dict[str, Any]:
    return build_closure_receipt(
        repository=ROOT,
        bounded_directory=ROOT / f"evidence/aws/bounded/{STAGE6_BOUNDED_RUN_ID}",
        recovery_directory=ROOT / f"evidence/aws/recovery/{STAGE6_RECOVERY_RUN_ID}",
        preflight_directory=preflight_directory,
        control_commit=control_commit,
    )


def command_preflight(arguments: argparse.Namespace) -> None:
    artifact = load_object(arguments.artifact_metadata)
    publish_preflight_evidence(
        raw_directory=arguments.raw_directory,
        output_directory=arguments.output_directory,
        artifact=artifact,
    )


def command_closure(arguments: argparse.Namespace) -> None:
    receipt = build_receipt(arguments.preflight_directory, arguments.control_commit)
    validate_closure_receipt(receipt, ROOT)
    write_json(arguments.output, receipt)


def command_verify(arguments: argparse.Namespace) -> None:
    receipt = load_object(arguments.receipt)
    validate_closure_receipt(receipt, ROOT)
    authority = receipt["clean_inventory_authority"]
    run_id = authority["run_id"]
    expected = build_receipt(
        ROOT / f"evidence/aws/preflight/{run_id}", receipt["closure_control_commit"]
    )
    if receipt != expected:
        raise ClosureError("committed closure receipt is not deterministic")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    commands = value.add_subparsers(dest="command", required=True)

    preflight = commands.add_parser("preflight")
    preflight.add_argument("--raw-directory", type=Path, required=True)
    preflight.add_argument("--output-directory", type=Path, required=True)
    preflight.add_argument("--artifact-metadata", type=Path, required=True)
    preflight.set_defaults(handler=command_preflight)

    closure = commands.add_parser("closure")
    closure.add_argument("--preflight-directory", type=Path, required=True)
    closure.add_argument("--control-commit", required=True)
    closure.add_argument("--output", type=Path, required=True)
    closure.set_defaults(handler=command_closure)

    verify = commands.add_parser("verify")
    verify.add_argument("--receipt", type=Path, required=True)
    verify.set_defaults(handler=command_verify)
    return value


def main() -> int:
    arguments = parser().parse_args()
    try:
        arguments.handler(arguments)
    except (ClosureError, OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        print(f"Part 4 Stage 7 evidence rejected: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
