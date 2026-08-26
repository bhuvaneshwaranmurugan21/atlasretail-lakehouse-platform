"""Tests for account-plan capture and its narrow AWS missing-data fallback."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "capture_account_plan.py"
SPEC = importlib.util.spec_from_file_location("capture_account_plan", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

ACCOUNT_ID = "857229544428"


def test_successful_lookup_is_marked_found() -> None:
    payload, error = MODULE.normalize_result(
        0,
        json.dumps({"accountPlanType": "PAID", "accountPlanStatus": "ACTIVE"}),
        "",
        ACCOUNT_ID,
    )

    assert error is None
    assert payload == {
        "accountPlanLookupResult": "FOUND",
        "accountPlanStatus": "ACTIVE",
        "accountPlanType": "PAID",
    }


def test_exact_missing_member_plan_is_safely_normalized() -> None:
    payload, error = MODULE.normalize_result(
        254,
        "",
        "ResourceNotFoundException: Missing data for account: 857229544428",
        ACCOUNT_ID,
    )

    assert error is None
    assert payload == {
        "accountId": ACCOUNT_ID,
        "accountPlanLookupResult": "NOT_FOUND",
        "errorCode": "ResourceNotFoundException",
    }


def test_other_aws_errors_remain_fatal() -> None:
    payload, error = MODULE.normalize_result(
        254,
        "",
        "AccessDeniedException: denied",
        ACCOUNT_ID,
    )

    assert payload is None
    assert error == "AccessDeniedException: denied"
