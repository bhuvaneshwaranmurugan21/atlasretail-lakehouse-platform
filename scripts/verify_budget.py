"""Validate the shared AWS budget and a conservative AtlasRetail run envelope."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

BUDGET_NAME = "portfolio-labs-monthly-cost"


def amount(value: object) -> tuple[float | None, str | None]:
    if not isinstance(value, dict):
        return None, None
    try:
        parsed = float(value.get("Amount"))
    except (TypeError, ValueError):
        parsed = None
    unit = value.get("Unit")
    return parsed, unit if isinstance(unit, str) else None


def verify(
    budget_payload: dict[str, Any],
    notification_payload: dict[str, Any],
    planned_ceiling_usd: float,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    budget = budget_payload.get("Budget", {})
    if not isinstance(budget, dict):
        budget = {}
    if budget.get("BudgetName") != BUDGET_NAME:
        errors.append("Shared portfolio budget is missing or has the wrong name")
    if budget.get("BudgetType") != "COST" or budget.get("TimeUnit") != "MONTHLY":
        errors.append("Shared portfolio budget must be a monthly COST budget")

    limit, limit_unit = amount(budget.get("BudgetLimit"))
    calculated = budget.get("CalculatedSpend", {})
    actual, actual_unit = amount(
        calculated.get("ActualSpend") if isinstance(calculated, dict) else None
    )
    if limit_unit != "USD" or limit is None or not 1 <= limit <= 100:
        errors.append("Budget limit must be between 1 and 100 USD")
    if actual_unit != "USD" or actual is None:
        errors.append("Current budget spend is unreadable or not denominated in USD")

    headroom = None if limit is None or actual is None else limit - actual
    if not 1 <= planned_ceiling_usd <= 10:
        errors.append("Planned gross cost ceiling must be between 1 and 10 USD")
    elif headroom is not None and headroom < planned_ceiling_usd:
        errors.append("Budget headroom is below the planned gross cost ceiling")

    notifications = notification_payload.get("Notifications")
    notification_count = len(notifications) if isinstance(notifications, list) else 0
    if notification_count == 0:
        warnings.append("Budget has no configured notifications; runtime bounds remain primary")

    return {
        "result": "PASS" if not errors else "FAIL",
        "budget_name": budget.get("BudgetName"),
        "budget_limit_usd": limit,
        "current_spend_usd": actual,
        "budget_headroom_usd": headroom,
        "planned_gross_cost_ceiling_usd": planned_ceiling_usd,
        "notification_count": notification_count,
        "warnings": warnings,
        "errors": errors,
    }


def main(arguments: list[str]) -> int:
    if len(arguments) != 5:
        print(
            "usage: verify_budget.py BUDGET_JSON NOTIFICATIONS_JSON OUTPUT_JSON CEILING_USD",
            file=sys.stderr,
        )
        return 2
    try:
        budget = json.loads(Path(arguments[1]).read_text(encoding="utf-8"))
        notifications = json.loads(Path(arguments[2]).read_text(encoding="utf-8"))
        ceiling = float(arguments[4])
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        print(f"budget input is unreadable: {error}", file=sys.stderr)
        return 2
    if not isinstance(budget, dict) or not isinstance(notifications, dict):
        print("budget inputs must be JSON objects", file=sys.stderr)
        return 2
    result = verify(budget, notifications, ceiling)
    output = Path(arguments[3])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
