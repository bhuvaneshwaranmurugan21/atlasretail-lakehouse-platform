#!/usr/bin/env python3
"""Validate an exact failed-recovery artifact before transferring its AWS lease."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _nested(value: dict[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def validate(
    summary: dict[str, Any],
    lease: dict[str, Any],
    lease_bytes: bytes,
    *,
    repository: str,
    failed_run_id: str,
    previous_recovery_run_id: str,
) -> dict[str, Any]:
    errors: list[str] = []
    expected_summary = {
        "project": "AtlasRetail",
        "proof": "failed-controlled-deployment-recovery",
        "recovery_run_id": previous_recovery_run_id,
        "failed_run_id": failed_run_id,
        "result": "FAIL",
        "claim": "NONE",
    }
    errors.extend(
        f"summary {name} mismatch"
        for name, expected in expected_summary.items()
        if summary.get(name) != expected
    )

    checks = summary.get("checks")
    if not isinstance(checks, dict):
        errors.append("summary checks must be an object")
        checks = {}
    if checks.get("immutable_authority") is not True:
        errors.append("prior immutable authority was not verified")
    if not isinstance(checks.get("saved_destroy_plan"), bool):
        errors.append("prior saved destroy plan result is not boolean")
    if checks.get("aws_and_terraform_clean") is not False:
        errors.append("prior recovery must not claim a clean teardown")

    expected_owner = f"{repository}/{previous_recovery_run_id}"
    if _nested(lease, "Item", "lock_id", "S") != "portfolio-lab":
        errors.append("prior lease lock id mismatch")
    if _nested(lease, "Item", "owner", "S") != expected_owner:
        errors.append("prior lease owner mismatch")
    expires_at = _nested(lease, "Item", "expires_at", "N")
    if not isinstance(expires_at, str) or not expires_at.isdigit():
        errors.append("prior lease expiry is not a numeric epoch")

    artifact_hashes = summary.get("artifact_hashes")
    expected_hash = (
        artifact_hashes.get("recovery-lease.json") if isinstance(artifact_hashes, dict) else None
    )
    observed_hash = "sha256:" + hashlib.sha256(lease_bytes).hexdigest()
    if expected_hash != observed_hash:
        errors.append("prior lease artifact hash mismatch")

    return {
        "result": "PASS" if not errors else "FAIL",
        "claim": "FAILED_RECOVERY_HANDOFF_VERIFIED" if not errors else "NONE",
        "repository": repository,
        "failed_run_id": failed_run_id,
        "previous_recovery_run_id": previous_recovery_run_id,
        "expected_lease_owner": expected_owner,
        "observed_lease_owner": _nested(lease, "Item", "owner", "S"),
        "prior_saved_destroy_plan": checks.get("saved_destroy_plan"),
        "expected_lease_hash": expected_hash,
        "observed_lease_hash": observed_hash,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--lease", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--failed-run-id", required=True)
    parser.add_argument("--previous-recovery-run-id", required=True)
    args = parser.parse_args()

    try:
        lease_bytes = args.lease.read_bytes()
        summary = json.loads(args.summary.read_text(encoding="utf-8"))
        lease = json.loads(lease_bytes)
        if not isinstance(summary, dict) or not isinstance(lease, dict):
            raise ValueError("summary and lease must be JSON objects")
        proof = validate(
            summary,
            lease,
            lease_bytes,
            repository=args.repository,
            failed_run_id=args.failed_run_id,
            previous_recovery_run_id=args.previous_recovery_run_id,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        proof = {"result": "FAIL", "claim": "NONE", "errors": [str(error)]}

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if proof["result"] != "PASS":
        print(json.dumps(proof, indent=2, sort_keys=True))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
