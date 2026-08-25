"""Tests for the fail-closed AWS paid-plan gate."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_account_plan.py"
SPEC = importlib.util.spec_from_file_location("verify_account_plan", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def payload(
    *, plan_type: str = "PAID", status: str = "ACTIVE", amount: float = 140.0
) -> dict[str, object]:
    return {
        "accountPlanType": plan_type,
        "accountPlanStatus": status,
        "accountPlanRemainingCredits": {"amount": amount, "unit": "USD"},
    }


def test_paid_active_plan_above_credit_floor_passes() -> None:
    result = MODULE.verify(payload(), 5.0)

    assert result["result"] == "PASS"
    assert result["remaining_credit_usd"] == 140.0


def test_free_plan_fails() -> None:
    result = MODULE.verify(payload(plan_type="FREE"), 5.0)

    assert result["result"] == "FAIL"
    assert "AWS account plan is not PAID" in result["errors"]


def test_inactive_plan_fails() -> None:
    result = MODULE.verify(payload(status="EXPIRED"), 5.0)

    assert result["result"] == "FAIL"
    assert "AWS account plan is not ACTIVE" in result["errors"]


def test_credit_below_run_ceiling_fails() -> None:
    result = MODULE.verify(payload(amount=4.99), 5.0)

    assert result["result"] == "FAIL"
    assert (
        "Neither member-account nor organization-shared credit covers the run ceiling"
        in result["errors"]
    )


def test_unreadable_credit_fails() -> None:
    value = payload()
    value["accountPlanRemainingCredits"] = {"amount": "unknown", "unit": "USD"}

    result = MODULE.verify(value, 5.0)

    assert result["result"] == "FAIL"
    assert result["credit_source"] is None


def shared_credit(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "1.0",
        "recipient_account_id": "857229544428",
        "verified_remaining_usd": 120,
        "credit_sharing_active": True,
        "credit_level_cost_category_restriction": False,
        "credit_expiration_date": "2027-08-25",
        "observed_at": "2026-08-25T00:00:00Z",
        "valid_until": "2026-09-01T23:59:59Z",
    }
    value.update(overrides)
    return value


def test_current_organization_shared_credit_replaces_zero_member_balance() -> None:
    result = MODULE.verify(
        payload(amount=0),
        5.0,
        shared_credit(),
        datetime(2026, 8, 25, 12, tzinfo=UTC),
    )

    assert result["result"] == "PASS"
    assert result["credit_source"] == "organization-shared"
    assert result["organization_shared_credit_usd"] == 120.0


def test_stale_organization_shared_credit_fails_closed() -> None:
    result = MODULE.verify(
        payload(amount=0),
        5.0,
        shared_credit(),
        datetime(2026, 9, 2, tzinfo=UTC),
    )

    assert result["result"] == "FAIL"
    assert "Organization-shared credit evidence is stale" in result["organization_credit_errors"]
