"""Build and validate attempt-bound Part 4 teardown authority."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from atlasretail.terraform_envelope import EXPECTED_DATA_ADDRESSES, EXPECTED_MANAGED_ADDRESSES

EXPECTED_ACCOUNT = "857229544428"
EXPECTED_REGION = "ap-southeast-2"
EXPECTED_REPOSITORY = "bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform"
EXPECTED_OWNER = "bhuvaneshwaranmurugan21"
EXPECTED_ROLE = f"arn:aws:iam::{EXPECTED_ACCOUNT}:role/AtlasRetailGitHubOidcRole"
EXPECTED_WORKFLOW = "AWS bounded lab"
EXPECTED_REF = "refs/heads/main"
EXPECTED_EVENT = "workflow_dispatch"
EXPECTED_CONTRACT_ID = "atlasretail-part4-bounded-execution"
EXPECTED_CONTRACT_VERSION = "1.0.0"
EXPECTED_TERRAFORM_VERSION = "1.11.4"
EXPECTED_BACKEND_KEY = "atlasretail/main.tfstate"
EXPECTED_TERRAFORM_LOCK_TABLE = "portfolio-lab-terraform-locks"
EXPECTED_LEASE_TABLE = "portfolio-lab-account-lease"
EXPECTED_LOCK_ID = "portfolio-lab"
INFRASTRUCTURE_DIGEST_SCHEME = "git-tracked-v2"


class AuthorityError(ValueError):
    """Raised when teardown authority is missing, ambiguous, or inconsistent."""


@dataclass(frozen=True)
class AuthorityContext:
    repository: str
    repository_owner: str
    workflow_name: str
    event: str
    ref: str
    actor: str
    source_commit: str
    run_id: str
    run_attempt: str
    order_count: int
    budget_ceiling_usd: int
    account_id: str
    region: str
    oidc_role_arn: str
    backend_bucket: str
    backend_key: str
    terraform_lock_table: str
    lease_table: str
    lease_owner: str
    terraform_version: str


@dataclass(frozen=True)
class AuthorityInputs:
    contract_id: str
    contract_version: str
    contract_sha256: str
    target_sha256: str
    authority_schema_sha256: str
    admission_receipt_sha256: str
    source_tree_sha256: str
    source_provenance_summary_sha256: str
    provider_lock_sha256: str
    infrastructure_digest: str
    apply_plan_json_sha256: str
    apply_plan_binary_sha256: str
    apply_plan_validation_sha256: str


def sha256_path(path: Path) -> str:
    """Return an unprefixed SHA-256 digest for one file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: object) -> str:
    """Digest the canonical JSON representation of a value."""
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    """Load a JSON object or raise a fail-closed authority error."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuthorityError(f"{path.name}: unreadable JSON: {error}") from error
    if not isinstance(value, dict):
        raise AuthorityError(f"{path.name}: expected a JSON object")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AuthorityError(message)


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    observed = set(value)
    if observed != expected:
        raise AuthorityError(
            f"{label}: keys differ; missing={sorted(expected - observed)}, "
            f"unexpected={sorted(observed - expected)}"
        )


def validate_context(context: AuthorityContext) -> None:
    """Validate immutable runtime bounds before authority construction."""
    expected = {
        "repository": (context.repository, EXPECTED_REPOSITORY),
        "repository_owner": (context.repository_owner, EXPECTED_OWNER),
        "workflow_name": (context.workflow_name, EXPECTED_WORKFLOW),
        "event": (context.event, EXPECTED_EVENT),
        "ref": (context.ref, EXPECTED_REF),
        "account_id": (context.account_id, EXPECTED_ACCOUNT),
        "region": (context.region, EXPECTED_REGION),
        "oidc_role_arn": (context.oidc_role_arn, EXPECTED_ROLE),
        "backend_key": (context.backend_key, EXPECTED_BACKEND_KEY),
        "terraform_lock_table": (
            context.terraform_lock_table,
            EXPECTED_TERRAFORM_LOCK_TABLE,
        ),
        "lease_table": (context.lease_table, EXPECTED_LEASE_TABLE),
        "terraform_version": (context.terraform_version, EXPECTED_TERRAFORM_VERSION),
    }
    for name, (observed, required) in expected.items():
        _require(observed == required, f"context: wrong {name}")
    _require(bool(context.actor), "context: actor is empty")
    _require(
        len(context.source_commit) == 40
        and all(character in "0123456789abcdef" for character in context.source_commit),
        "context: source commit is invalid",
    )
    for name, value in (("run_id", context.run_id), ("run_attempt", context.run_attempt)):
        _require(value.isdigit() and int(value) > 0, f"context: {name} is invalid")
    _require(100 <= context.order_count <= 2000, "context: order count is out of bounds")
    _require(
        1 <= context.budget_ceiling_usd <= 5,
        "context: budget ceiling is out of bounds",
    )
    _require(bool(context.backend_bucket), "context: backend bucket is empty")
    _require(
        context.lease_owner == f"{context.repository}/{context.run_id}/{context.run_attempt}",
        "context: lease owner is not attempt-bound",
    )


def validate_admission(receipt: dict[str, Any], context: AuthorityContext) -> None:
    """Correlate the already-validated admission receipt to authority inputs."""
    _require(receipt.get("result") == "PASS", "admission receipt did not pass")
    workflow = receipt.get("workflow")
    bindings = receipt.get("bindings")
    bounds = receipt.get("bounds")
    sources = receipt.get("sources")
    if not isinstance(workflow, dict):
        raise AuthorityError("admission workflow is absent")
    if not isinstance(bindings, dict):
        raise AuthorityError("admission bindings are absent")
    if not isinstance(bounds, dict):
        raise AuthorityError("admission bounds are absent")
    if not isinstance(sources, dict):
        raise AuthorityError("admission source bindings are absent")
    expected_workflow: dict[str, object] = {
        "repository": context.repository,
        "repository_owner": context.repository_owner,
        "workflow_name": context.workflow_name,
        "event": context.event,
        "ref": context.ref,
        "actor": context.actor,
        "source_commit": context.source_commit,
        "run_id": context.run_id,
        "run_attempt": context.run_attempt,
    }
    for name, expected in expected_workflow.items():
        _require(workflow.get(name) == expected, f"admission receipt has wrong {name}")
    _require(bounds.get("order_count") == context.order_count, "admission order count differs")
    _require(
        bounds.get("budget_ceiling_usd") == context.budget_ceiling_usd,
        "admission budget ceiling differs",
    )
    _require(
        bindings.get("aws_account_id") == context.account_id
        and bindings.get("aws_region") == context.region
        and bindings.get("oidc_role_arn") == context.oidc_role_arn,
        "admission AWS binding differs",
    )


def validate_plan_receipt(receipt: dict[str, Any]) -> None:
    """Require a successful exact 40-address saved apply-plan validation."""
    _require(receipt.get("result") == "PASS", "apply-plan validation did not pass")
    _require(receipt.get("mode") == "apply", "apply-plan validation has wrong mode")
    _require(receipt.get("exact_envelope") is True, "apply plan was not exact-envelope validated")
    _require(
        receipt.get("partial_destroy_recovery") is False,
        "apply-plan validation incorrectly permits partial destroy",
    )
    _require(receipt.get("resource_count") == 40, "apply plan does not contain 40 resources")
    _require(not receipt.get("errors"), "apply-plan validation contains errors")


def build_authority(
    context: AuthorityContext,
    inputs: AuthorityInputs,
    admission: dict[str, Any],
    plan_validation: dict[str, Any],
    *,
    created_at: str,
) -> dict[str, Any]:
    """Build one exact authority after validating all bound inputs."""
    validate_context(context)
    validate_admission(admission, context)
    validate_plan_receipt(plan_validation)
    _require(inputs.contract_id == EXPECTED_CONTRACT_ID, "wrong contract ID")
    _require(inputs.contract_version == EXPECTED_CONTRACT_VERSION, "wrong contract version")
    _require(
        inputs.infrastructure_digest.startswith("sha256:")
        and len(inputs.infrastructure_digest) == 71,
        "infrastructure digest is invalid",
    )
    try:
        parsed_created_at = datetime.fromisoformat(created_at)
    except ValueError as error:
        raise AuthorityError("authority creation timestamp is invalid") from error
    _require(parsed_created_at.utcoffset() is not None, "authority timestamp is not timezone-aware")
    workflow = admission["workflow"]
    sources = admission["sources"]
    bindings = admission["bindings"]
    _require(bindings.get("contract_id") == inputs.contract_id, "admission contract ID differs")
    _require(
        bindings.get("contract_version") == inputs.contract_version,
        "admission contract version differs",
    )
    _require(
        bindings.get("contract_sha256") == inputs.contract_sha256,
        "admission contract digest differs",
    )
    _require(
        bindings.get("target_sha256") == inputs.target_sha256,
        "admission target digest differs",
    )
    _require(
        sources.get("source_tree_sha256") == inputs.source_tree_sha256,
        "admission source tree digest differs",
    )
    _require(
        sources.get("source_provenance_summary_sha256") == inputs.source_provenance_summary_sha256,
        "admission source provenance digest differs",
    )
    _require(workflow.get("run_attempt") == context.run_attempt, "admission attempt differs")
    return {
        "schema_version": "1.0",
        "proof": "part4-teardown-authority",
        "result": "PASS",
        "project": "AtlasRetail",
        "operation": "bounded-lab-teardown",
        "execution_class": "BOUNDED_NON_PRODUCTION_LAB",
        "created_at": created_at,
        "workflow": {
            "repository": context.repository,
            "repository_owner": context.repository_owner,
            "workflow_name": context.workflow_name,
            "event": context.event,
            "ref": context.ref,
            "actor": context.actor,
            "source_commit": context.source_commit,
            "run_id": context.run_id,
            "run_attempt": context.run_attempt,
        },
        "bindings": {
            "contract_id": inputs.contract_id,
            "contract_version": inputs.contract_version,
            "contract_sha256": inputs.contract_sha256,
            "target_sha256": inputs.target_sha256,
            "authority_schema_sha256": inputs.authority_schema_sha256,
            "admission_receipt_sha256": inputs.admission_receipt_sha256,
            "source_tree_sha256": inputs.source_tree_sha256,
            "source_provenance_summary_sha256": inputs.source_provenance_summary_sha256,
        },
        "aws": {
            "account_id": context.account_id,
            "region": context.region,
            "oidc_role_arn": context.oidc_role_arn,
        },
        "terraform": {
            "version": context.terraform_version,
            "provider_lock_sha256": inputs.provider_lock_sha256,
            "infrastructure_digest_scheme": INFRASTRUCTURE_DIGEST_SCHEME,
            "infrastructure_digest": inputs.infrastructure_digest,
            "backend_bucket": context.backend_bucket,
            "backend_key": context.backend_key,
            "backend_region": context.region,
            "lock_table": context.terraform_lock_table,
            "apply_plan_json_sha256": inputs.apply_plan_json_sha256,
            "apply_plan_binary_sha256": inputs.apply_plan_binary_sha256,
            "apply_plan_validation_sha256": inputs.apply_plan_validation_sha256,
            "managed_addresses": sorted(EXPECTED_MANAGED_ADDRESSES),
            "read_only_data_addresses": sorted(EXPECTED_DATA_ADDRESSES),
        },
        "lease": {
            "table": context.lease_table,
            "lock_id": EXPECTED_LOCK_ID,
            "owner": context.lease_owner,
        },
        "bounds": {
            "order_count": context.order_count,
            "budget_ceiling_usd": context.budget_ceiling_usd,
            "runtime_expansion_prohibited": True,
        },
    }


TOP_LEVEL_KEYS = {
    "schema_version",
    "proof",
    "result",
    "project",
    "operation",
    "execution_class",
    "created_at",
    "workflow",
    "bindings",
    "aws",
    "terraform",
    "lease",
    "bounds",
}


def validate_authority(
    authority: dict[str, Any],
    context: AuthorityContext,
    inputs: AuthorityInputs,
    admission: dict[str, Any],
    plan_validation: dict[str, Any],
) -> dict[str, Any]:
    """Recompute and compare an authority without trusting its bound values."""
    _exact_keys(authority, TOP_LEVEL_KEYS, "authority")
    created_at = authority.get("created_at")
    if not isinstance(created_at, str):
        raise AuthorityError("authority creation timestamp is absent")
    expected = build_authority(
        context,
        inputs,
        admission,
        plan_validation,
        created_at=created_at,
    )
    _require(authority == expected, "authority differs from independently recomputed value")
    return {
        "schema_version": "1.0",
        "proof": "part4-teardown-authority-verification",
        "result": "PASS",
        "claim_level": "LOCAL_VERIFIED",
        "aws_execution": False,
        "authority_sha256": canonical_sha256(authority),
        "repository": context.repository,
        "source_commit": context.source_commit,
        "run_id": context.run_id,
        "run_attempt": context.run_attempt,
        "lease_owner": context.lease_owner,
        "managed_address_count": len(EXPECTED_MANAGED_ADDRESSES),
        "read_only_data_address_count": len(EXPECTED_DATA_ADDRESSES),
    }
