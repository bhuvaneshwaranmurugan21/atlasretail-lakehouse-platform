"""Tests for the fail-closed AWS paid-plan gate."""

from __future__ import annotations

import importlib.util
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
    assert "Remaining account credits are below the bounded run cost ceiling" in result["errors"]


def test_unreadable_credit_fails() -> None:
    value = payload()
    value["accountPlanRemainingCredits"] = {"amount": "unknown", "unit": "USD"}

    result = MODULE.verify(value, 5.0)

    assert result["result"] == "FAIL"
    assert "Remaining account credits are unreadable or not denominated in USD" in result["errors"]
