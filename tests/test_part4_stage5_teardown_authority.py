"""Positive and adversarial tests for immutable Part 4 teardown authority."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest

from atlasretail.part4_teardown_authority import (
    EXPECTED_ACCOUNT,
    EXPECTED_BACKEND_KEY,
    EXPECTED_CONTRACT_ID,
    EXPECTED_CONTRACT_VERSION,
    EXPECTED_EVENT,
    EXPECTED_LEASE_TABLE,
    EXPECTED_OWNER,
    EXPECTED_REF,
    EXPECTED_REGION,
    EXPECTED_REPOSITORY,
    EXPECTED_ROLE,
    EXPECTED_TERRAFORM_LOCK_TABLE,
    EXPECTED_TERRAFORM_VERSION,
    EXPECTED_WORKFLOW,
    AuthorityContext,
    AuthorityError,
    AuthorityInputs,
    build_authority,
    validate_authority,
)

RUN_ID = "424242"
RUN_ATTEMPT = "3"
SOURCE_COMMIT = "a" * 40
LEASE_OWNER = f"{EXPECTED_REPOSITORY}/{RUN_ID}/{RUN_ATTEMPT}"
CREATED_AT = "2026-08-30T10:00:00+00:00"


def context() -> AuthorityContext:
    return AuthorityContext(
        repository=EXPECTED_REPOSITORY,
        repository_owner=EXPECTED_OWNER,
        workflow_name=EXPECTED_WORKFLOW,
        event=EXPECTED_EVENT,
        ref=EXPECTED_REF,
        actor=EXPECTED_OWNER,
        source_commit=SOURCE_COMMIT,
        run_id=RUN_ID,
        run_attempt=RUN_ATTEMPT,
        order_count=500,
        budget_ceiling_usd=5,
        account_id=EXPECTED_ACCOUNT,
        region=EXPECTED_REGION,
        oidc_role_arn=EXPECTED_ROLE,
        backend_bucket="portfolio-lab-tfstate-857229544428-ap-southeast-2",
        backend_key=EXPECTED_BACKEND_KEY,
        terraform_lock_table=EXPECTED_TERRAFORM_LOCK_TABLE,
        lease_table=EXPECTED_LEASE_TABLE,
        lease_owner=LEASE_OWNER,
        terraform_version=EXPECTED_TERRAFORM_VERSION,
    )


def inputs() -> AuthorityInputs:
    return AuthorityInputs(
        contract_id=EXPECTED_CONTRACT_ID,
        contract_version=EXPECTED_CONTRACT_VERSION,
        contract_sha256="1" * 64,
        target_sha256="2" * 64,
        authority_schema_sha256="3" * 64,
        admission_receipt_sha256="4" * 64,
        source_tree_sha256="5" * 64,
        source_provenance_summary_sha256="6" * 64,
        provider_lock_sha256="7" * 64,
        infrastructure_digest="sha256:" + "8" * 64,
        apply_plan_json_sha256="9" * 64,
        apply_plan_binary_sha256="a" * 64,
        apply_plan_validation_sha256="b" * 64,
    )


def admission() -> dict[str, Any]:
    return {
        "result": "PASS",
        "workflow": {
            "repository": EXPECTED_REPOSITORY,
            "repository_owner": EXPECTED_OWNER,
            "workflow_name": EXPECTED_WORKFLOW,
            "event": EXPECTED_EVENT,
            "ref": EXPECTED_REF,
            "actor": EXPECTED_OWNER,
            "source_commit": SOURCE_COMMIT,
            "run_id": RUN_ID,
            "run_attempt": RUN_ATTEMPT,
        },
        "bindings": {
            "contract_id": EXPECTED_CONTRACT_ID,
            "contract_version": EXPECTED_CONTRACT_VERSION,
            "contract_sha256": "1" * 64,
            "target_sha256": "2" * 64,
            "aws_account_id": EXPECTED_ACCOUNT,
            "aws_region": EXPECTED_REGION,
            "oidc_role_arn": EXPECTED_ROLE,
        },
        "bounds": {"order_count": 500, "budget_ceiling_usd": 5},
        "sources": {
            "source_tree_sha256": "5" * 64,
            "source_provenance_summary_sha256": "6" * 64,
        },
    }


def plan_validation() -> dict[str, Any]:
    return {
        "result": "PASS",
        "mode": "apply",
        "exact_envelope": True,
        "partial_destroy_recovery": False,
        "resource_count": 40,
        "errors": [],
    }


def built() -> dict[str, Any]:
    return build_authority(
        context(), inputs(), admission(), plan_validation(), created_at=CREATED_AT
    )


def test_authority_binds_exact_attempt_plan_target_backend_and_lease() -> None:
    authority = built()
    proof = validate_authority(authority, context(), inputs(), admission(), plan_validation())

    assert proof["result"] == "PASS"
    assert proof["claim_level"] == "LOCAL_VERIFIED"
    assert proof["aws_execution"] is False
    assert proof["run_attempt"] == RUN_ATTEMPT
    assert proof["lease_owner"] == LEASE_OWNER
    assert proof["managed_address_count"] == 40
    assert proof["read_only_data_address_count"] == 6
    assert authority["terraform"]["apply_plan_json_sha256"] == "9" * 64
    assert authority["terraform"]["backend_key"] == EXPECTED_BACKEND_KEY


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("repository", "someone/else", "wrong repository"),
        ("repository_owner", "someone", "wrong repository_owner"),
        ("workflow_name", "Other", "wrong workflow_name"),
        ("event", "push", "wrong event"),
        ("ref", "refs/heads/feature", "wrong ref"),
        ("source_commit", "not-a-sha", "source commit"),
        ("run_id", "0", "run_id"),
        ("run_attempt", "0", "run_attempt"),
        ("order_count", 2001, "order count"),
        ("budget_ceiling_usd", 6, "budget ceiling"),
        ("account_id", "000000000000", "wrong account_id"),
        ("region", "ap-" + "south-1", "wrong region"),
        ("oidc_role_arn", "arn:aws:iam::0:role/other", "wrong oidc_role_arn"),
        ("backend_key", "other.tfstate", "wrong backend_key"),
        ("terraform_lock_table", "other", "wrong terraform_lock_table"),
        ("lease_table", "other", "wrong lease_table"),
        ("lease_owner", f"{EXPECTED_REPOSITORY}/{RUN_ID}", "attempt-bound"),
        ("terraform_version", "1.12.0", "wrong terraform_version"),
    ],
)
def test_invalid_context_fails_before_authority(field: str, value: object, message: str) -> None:
    with pytest.raises(AuthorityError, match=message):
        build_authority(
            replace(context(), **{field: value}),
            inputs(),
            admission(),
            plan_validation(),
            created_at=CREATED_AT,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["workflow"].update({"run_attempt": "4"}),
            "authority differs",
        ),
        (
            lambda value: value["bindings"].update({"contract_sha256": "0" * 64}),
            "authority differs",
        ),
        (
            lambda value: value["bindings"].update({"target_sha256": "0" * 64}),
            "authority differs",
        ),
        (
            lambda value: value["terraform"].update({"backend_key": "other.tfstate"}),
            "authority differs",
        ),
        (
            lambda value: value["terraform"].update({"apply_plan_json_sha256": "0" * 64}),
            "authority differs",
        ),
        (
            lambda value: value["terraform"]["managed_addresses"].pop(),
            "authority differs",
        ),
        (
            lambda value: value["lease"].update({"owner": "stale-owner"}),
            "authority differs",
        ),
        (
            lambda value: value.update({"unexpected": True}),
            "keys differ",
        ),
    ],
)
def test_authority_substitution_fails_closed(
    mutation: Callable[[dict[str, Any]], None], message: str
) -> None:
    authority = copy.deepcopy(built())
    mutation(authority)

    with pytest.raises(AuthorityError, match=message):
        validate_authority(authority, context(), inputs(), admission(), plan_validation())


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update({"result": "FAIL"}), "did not pass"),
        (lambda value: value.update({"mode": "destroy"}), "wrong mode"),
        (lambda value: value.update({"exact_envelope": False}), "not exact-envelope"),
        (lambda value: value.update({"resource_count": 39}), "40 resources"),
        (lambda value: value.update({"errors": ["bad"]}), "contains errors"),
    ],
)
def test_non_exact_apply_plan_cannot_authorize_teardown(
    mutation: Callable[[dict[str, Any]], None], message: str
) -> None:
    receipt = plan_validation()
    mutation(receipt)

    with pytest.raises(AuthorityError, match=message):
        build_authority(context(), inputs(), admission(), receipt, created_at=CREATED_AT)


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(AuthorityError, match="timezone-aware"):
        build_authority(
            context(), inputs(), admission(), plan_validation(), created_at="2026-08-30T10:00:00"
        )
