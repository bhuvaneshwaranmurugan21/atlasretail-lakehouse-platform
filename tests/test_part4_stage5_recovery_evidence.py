"""Adversarial tests for exact-authority Part 4 recovery evidence."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "summarize_part4_recovery", ROOT / "scripts/summarize_part4_recovery.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

REPOSITORY = "bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform"
FAILED_RUN = "111"
FAILED_ATTEMPT = "2"
FAILED_SOURCE = "a" * 40
RECOVERY_RUN = "222"
RECOVERY_ATTEMPT = "1"


def write(root: Path, name: str, value: object) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def complete(root: Path) -> None:
    failed_owner = f"{REPOSITORY}/{FAILED_RUN}/{FAILED_ATTEMPT}"
    recovery_owner = f"{REPOSITORY}/{RECOVERY_RUN}/{RECOVERY_ATTEMPT}"
    write(
        root,
        "teardown-authority.json",
        {
            "workflow": {
                "repository": REPOSITORY,
                "run_id": FAILED_RUN,
                "run_attempt": FAILED_ATTEMPT,
                "source_commit": FAILED_SOURCE,
            },
            "lease": {"owner": failed_owner},
        },
    )
    authority_sha = hashlib.sha256((root / "teardown-authority.json").read_bytes()).hexdigest()
    write(
        root,
        "teardown-authority-digest.json",
        {"result": "PASS", "authority_sha256": authority_sha},
    )
    write(
        root,
        "recovery-authority-verification.json",
        {
            "result": "PASS",
            "authority_file_sha256": authority_sha,
            "authority_bound_recovery_mode": True,
            "plan_files_revalidated": False,
        },
    )
    write(root, "recovery-session-policy.json", {"Statement": [{"Effect": "Deny"}]})
    policy_sha = hashlib.sha256((root / "recovery-session-policy.json").read_bytes()).hexdigest()
    write(
        root,
        "recovery-session-receipt.json",
        {
            "result": "PASS",
            "aws_account_id": "857229544428",
            "aws_region": "ap-southeast-2",
            "role_arn": "arn:aws:iam::857229544428:role/AtlasRetailGitHubOidcRole",
            "session_policy_sha256": policy_sha,
            "cleanup_only": True,
            "workload_execution": False,
        },
    )
    write(
        root,
        "recovery-lease-binding.json",
        {
            "result": "PASS",
            "mode": "EXACT_OWNER_TRANSITION",
            "failed_owner": failed_owner,
            "owner": recovery_owner,
            "run_attempt": FAILED_ATTEMPT,
            "source_commit": FAILED_SOURCE,
            "state": "RECOVERY_BOUND",
            "authority_sha256": authority_sha,
            "consistent_read": True,
        },
    )
    write(
        root,
        "terraform-recovery-destroy-plan-validation.json",
        {
            "result": "PASS",
            "mode": "destroy",
            "partial_destroy_recovery": True,
            "exact_envelope": False,
        },
    )
    write(root, "recovery-teardown.json", {"result": "PASS", "checks": [{"deleted": True}]})
    write(root, "post-recovery-budget-verification.json", {"result": "PASS"})
    write(
        root,
        "recovery-lease-release.json",
        {
            "result": "PASS",
            "owner": recovery_owner,
            "run_attempt": FAILED_ATTEMPT,
            "source_commit": FAILED_SOURCE,
            "authority_sha256": authority_sha,
            "lease_absent": True,
            "consistent_read": True,
        },
    )


def summarize(root: Path) -> dict[str, Any]:
    return MODULE.summarize(
        root,
        failed_run_id=FAILED_RUN,
        failed_run_attempt=FAILED_ATTEMPT,
        failed_source_commit=FAILED_SOURCE,
        recovery_run_id=RECOVERY_RUN,
        recovery_run_attempt=RECOVERY_ATTEMPT,
        repository=REPOSITORY,
    )


def mutate(root: Path, name: str, change: Any) -> None:
    path = root / name
    value = json.loads(path.read_text(encoding="utf-8"))
    change(value)
    write(root, name, value)


def test_complete_exact_recovery_is_aws_verified_cleanup_only(tmp_path: Path) -> None:
    complete(tmp_path)

    result = summarize(tmp_path)

    assert result["result"] == "PASS"
    assert result["claim_level"] == "AWS_VERIFIED"
    assert result["cleanup_only"] is True
    assert result["workload_execution"] is False
    assert result["teardown_complete"] is True
    assert result["lease_released"] is True


def test_already_clean_recovery_releases_exact_lease_without_destroy(tmp_path: Path) -> None:
    complete(tmp_path)
    (tmp_path / "terraform-recovery-destroy-plan-validation.json").unlink()
    (tmp_path / "recovery-teardown.json").unlink()
    write(tmp_path, "recovery-clean-no-deployment.json", {"result": "PASS"})

    result = summarize(tmp_path)

    assert result["result"] == "PASS"
    assert result["cleanup_mode"] == "ALREADY_CLEAN"
    assert result["teardown_complete"] is True


@pytest.mark.parametrize(
    ("name", "change", "message"),
    [
        (
            "teardown-authority.json",
            lambda value: value["workflow"].update({"run_attempt": "3"}),
            "authority digest differs",
        ),
        (
            "recovery-authority-verification.json",
            lambda value: value.update({"authority_bound_recovery_mode": False}),
            "not validated in recovery mode",
        ),
        (
            "recovery-session-receipt.json",
            lambda value: value.update({"workload_execution": True}),
            "not cleanup-only",
        ),
        (
            "recovery-lease-binding.json",
            lambda value: value.update({"failed_owner": "substituted"}),
            "wrong failed_owner",
        ),
        (
            "terraform-recovery-destroy-plan-validation.json",
            lambda value: value.update({"partial_destroy_recovery": False}),
            "bounded partial envelope",
        ),
        (
            "recovery-teardown.json",
            lambda value: value["checks"][0].update({"deleted": False}),
            "unproved inventory",
        ),
        (
            "post-recovery-budget-verification.json",
            lambda value: value.update({"result": "FAIL"}),
            "budget did not pass",
        ),
        (
            "recovery-lease-release.json",
            lambda value: value.update({"lease_absent": False}),
            "wrong lease_absent",
        ),
    ],
)
def test_recovery_evidence_rejects_substitution_or_missing_proof(
    tmp_path: Path, name: str, change: Any, message: str
) -> None:
    complete(tmp_path)
    mutate(tmp_path, name, change)

    result = summarize(tmp_path)

    assert result["result"] == "FAIL"
    assert result["claim_level"] == "UNCLAIMED"
    assert any(message in error for error in result["errors"])


def test_missing_release_never_claims_recovery_success(tmp_path: Path) -> None:
    complete(tmp_path)
    (tmp_path / "recovery-lease-release.json").unlink()

    result = summarize(tmp_path)

    assert result["result"] == "FAIL"
    assert result["lease_released"] is False
