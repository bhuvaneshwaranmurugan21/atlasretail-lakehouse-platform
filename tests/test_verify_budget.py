from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_budget.py"
SPEC = importlib.util.spec_from_file_location("verify_budget", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def budget(limit: str = "20", actual: str = "1.25") -> dict[str, object]:
    return {
        "Budget": {
            "BudgetName": MODULE.BUDGET_NAME,
            "BudgetType": "COST",
            "TimeUnit": "MONTHLY",
            "BudgetLimit": {"Amount": limit, "Unit": "USD"},
            "CalculatedSpend": {"ActualSpend": {"Amount": actual, "Unit": "USD"}},
        }
    }


def test_budget_headroom_and_notifications_pass() -> None:
    result = MODULE.verify(budget(), {"Notifications": [{"Threshold": 50}]}, 5)

    assert result["result"] == "PASS"
    assert result["budget_headroom_usd"] == 18.75
    assert result["notification_count"] == 1
    assert result["warnings"] == []


def test_insufficient_headroom_fails_closed() -> None:
    result = MODULE.verify(budget(limit="5", actual="2"), {"Notifications": []}, 5)

    assert result["result"] == "FAIL"
    assert "headroom" in result["errors"][0]


def test_missing_notifications_fail_closed() -> None:
    result = MODULE.verify(budget(), {"Notifications": []}, 5)

    assert result["result"] == "FAIL"
    assert "notifications" in result["errors"][-1]
