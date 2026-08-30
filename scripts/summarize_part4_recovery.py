#!/usr/bin/env python3
"""Fail closed unless a Part 4 recovery proves exact-authority teardown."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

EXPECTED_ACCOUNT = "857229544428"
EXPECTED_REGION = "ap-southeast-2"
EXPECTED_ROLE = f"arn:aws:iam::{EXPECTED_ACCOUNT}:role/AtlasRetailGitHubOidcRole"


def load_object(path: Path, errors: list[str]) -> dict[str, Any]:
    """Load one required JSON object and preserve an actionable failure."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"{path.name}: unreadable JSON: {error}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{path.name}: expected a JSON object")
        return {}
    return value


def require(condition: bool, message: str, errors: list[str]) -> None:
    """Append a deterministic error when a recovery invariant is false."""
    if not condition:
        errors.append(message)


def sha256(path: Path) -> str:
    """Return an unprefixed SHA-256 digest."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(
    root: Path,
    *,
    failed_run_id: str,
    failed_run_attempt: str,
    failed_source_commit: str,
    recovery_run_id: str,
    recovery_run_attempt: str,
    repository: str,
) -> dict[str, Any]:
    """Validate exact failed-run cleanup and return an auditable summary."""
    errors: list[str] = []
    failed_owner = f"{repository}/{failed_run_id}/{failed_run_attempt}"
    recovery_owner = f"{repository}/{recovery_run_id}/{recovery_run_attempt}"

    authority_path = root / "teardown-authority.json"
    digest = load_object(root / "teardown-authority-digest.json", errors)
    authority = load_object(authority_path, errors)
    authority_validation = load_object(root / "recovery-authority-verification.json", errors)
    session_policy_path = root / "recovery-session-policy.json"
    session_receipt = load_object(root / "recovery-session-receipt.json", errors)
    lease_binding = load_object(root / "recovery-lease-binding.json", errors)
    clean_path = root / "recovery-clean-no-deployment.json"
    destroy_path = root / "terraform-recovery-destroy-plan-validation.json"
    teardown_path = root / "recovery-teardown.json"
    clean_mode = clean_path.is_file()
    destroy_mode = destroy_path.is_file() or teardown_path.is_file()
    require(clean_mode != destroy_mode, "recovery cleanup mode is absent or ambiguous", errors)
    clean = load_object(clean_path, errors) if clean_mode else {}
    destroy_validation = load_object(destroy_path, errors) if destroy_mode else {}
    teardown = load_object(teardown_path, errors) if destroy_mode else {}
    budget = load_object(root / "post-recovery-budget-verification.json", errors)
    release = load_object(root / "recovery-lease-release.json", errors)

    authority_sha = ""
    try:
        authority_sha = sha256(authority_path)
    except OSError as error:
        errors.append(f"teardown-authority.json: unreadable bytes: {error}")
    require(digest.get("result") == "PASS", "authority digest receipt did not pass", errors)
    require(
        digest.get("authority_sha256") == authority_sha,
        "authority digest differs from the exact recovered bytes",
        errors,
    )

    workflow = authority.get("workflow")
    workflow = workflow if isinstance(workflow, dict) else {}
    require(workflow.get("repository") == repository, "authority repository differs", errors)
    require(workflow.get("run_id") == failed_run_id, "authority failed run differs", errors)
    require(
        workflow.get("run_attempt") == failed_run_attempt,
        "authority failed attempt differs",
        errors,
    )
    require(
        workflow.get("source_commit") == failed_source_commit,
        "authority failed source differs",
        errors,
    )
    require(
        authority.get("lease", {}).get("owner") == failed_owner
        if isinstance(authority.get("lease"), dict)
        else False,
        "authority failed lease owner differs",
        errors,
    )
    require(
        authority_validation.get("result") == "PASS",
        "independent authority validation did not pass",
        errors,
    )
    require(
        authority_validation.get("authority_file_sha256") == authority_sha,
        "authority validation digest differs",
        errors,
    )
    require(
        authority_validation.get("authority_bound_recovery_mode") is True,
        "authority was not validated in recovery mode",
        errors,
    )
    require(
        authority_validation.get("plan_files_revalidated") is False,
        "recovery unexpectedly claims original plan-file revalidation",
        errors,
    )

    try:
        policy_sha = sha256(session_policy_path)
    except OSError as error:
        errors.append(f"recovery-session-policy.json: unreadable bytes: {error}")
        policy_sha = ""
    require(session_receipt.get("result") == "PASS", "recovery session did not pass", errors)
    require(
        session_receipt.get("aws_account_id") == EXPECTED_ACCOUNT,
        "recovery session account differs",
        errors,
    )
    require(
        session_receipt.get("aws_region") == EXPECTED_REGION,
        "recovery session region differs",
        errors,
    )
    require(
        session_receipt.get("role_arn") == EXPECTED_ROLE,
        "recovery session role differs",
        errors,
    )
    require(
        session_receipt.get("session_policy_sha256") == policy_sha,
        "recovery session policy digest differs",
        errors,
    )
    require(
        session_receipt.get("cleanup_only") is True
        and session_receipt.get("workload_execution") is False,
        "recovery session is not cleanup-only",
        errors,
    )

    expected_binding = {
        "result": "PASS",
        "failed_owner": failed_owner,
        "owner": recovery_owner,
        "run_attempt": failed_run_attempt,
        "source_commit": failed_source_commit,
        "state": "RECOVERY_BOUND",
        "authority_sha256": authority_sha,
        "consistent_read": True,
    }
    for name, expected in expected_binding.items():
        require(
            lease_binding.get(name) == expected,
            f"recovery lease binding has wrong {name}",
            errors,
        )
    require(
        lease_binding.get("mode")
        in {
            "EXACT_OWNER_TRANSITION",
            "ABSENT_LEASE_RECOVERY_ACQUISITION",
        },
        "recovery lease transition mode is invalid",
        errors,
    )

    if destroy_mode:
        require(
            destroy_validation.get("result") == "PASS"
            and destroy_validation.get("mode") == "destroy"
            and destroy_validation.get("partial_destroy_recovery") is True
            and destroy_validation.get("exact_envelope") is False,
            "saved recovery destroy plan did not pass the bounded partial envelope",
            errors,
        )
        checks = teardown.get("checks")
        require(teardown.get("result") == "PASS", "recovery teardown did not pass", errors)
        require(
            isinstance(checks, list)
            and bool(checks)
            and all(isinstance(check, dict) and check.get("deleted") is True for check in checks),
            "recovery teardown contains an unproved inventory check",
            errors,
        )
    else:
        require(
            clean.get("result") == "PASS",
            "already-clean recovery inventory did not pass",
            errors,
        )
    require(budget.get("result") == "PASS", "post-recovery budget did not pass", errors)

    expected_release = {
        "result": "PASS",
        "owner": recovery_owner,
        "run_attempt": failed_run_attempt,
        "source_commit": failed_source_commit,
        "authority_sha256": authority_sha,
        "lease_absent": True,
        "consistent_read": True,
    }
    for name, expected in expected_release.items():
        require(release.get(name) == expected, f"recovery lease release has wrong {name}", errors)

    artifacts: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "recovery-summary.json":
            artifacts[path.relative_to(root).as_posix()] = f"sha256:{sha256(path)}"

    passed = not errors
    return {
        "schema_version": "1.0",
        "proof": "part4-bounded-lab-deterministic-recovery",
        "result": "PASS" if passed else "FAIL",
        "claim_level": "AWS_VERIFIED" if passed else "UNCLAIMED",
        "aws_execution": True,
        "cleanup_only": True,
        "workload_execution": False,
        "cleanup_mode": "ALREADY_CLEAN" if clean_mode else "DESTROY_APPLIED",
        "failed_run_id": failed_run_id,
        "failed_run_attempt": failed_run_attempt,
        "failed_source_commit": failed_source_commit,
        "recovery_run_id": recovery_run_id,
        "recovery_run_attempt": recovery_run_attempt,
        "authority_sha256": authority_sha or None,
        "lease_released": release.get("lease_absent") is True,
        "teardown_complete": (
            clean.get("result") == "PASS" if clean_mode else teardown.get("result") == "PASS"
        ),
        "artifact_hashes": artifacts,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-directory", type=Path, required=True)
    parser.add_argument("--failed-run-id", required=True)
    parser.add_argument("--failed-run-attempt", required=True)
    parser.add_argument("--failed-source-commit", required=True)
    parser.add_argument("--recovery-run-id", required=True)
    parser.add_argument("--recovery-run-attempt", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = summarize(
        args.evidence_directory,
        failed_run_id=args.failed_run_id,
        failed_run_attempt=args.failed_run_attempt,
        failed_source_commit=args.failed_source_commit,
        recovery_run_id=args.recovery_run_id,
        recovery_run_attempt=args.recovery_run_attempt,
        repository=args.repository,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if result["result"] != "PASS":
        print(json.dumps(result, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
