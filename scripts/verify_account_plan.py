"""Fail closed unless the AWS account can run the bounded paid-plan lab."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def verify(payload: dict[str, Any], minimum_credit_usd: float) -> dict[str, Any]:
    """Validate plan state and the bounded run's credit floor."""
    errors: list[str] = []
    plan_type = payload.get("accountPlanType")
    plan_status = payload.get("accountPlanStatus")
    credit = payload.get("accountPlanRemainingCredits")

    if plan_type != "PAID":
        errors.append("AWS account plan is not PAID")
    if plan_status != "ACTIVE":
        errors.append("AWS account plan is not ACTIVE")

    amount: float | None = None
    unit: str | None = None
    if isinstance(credit, dict):
        unit_value = credit.get("unit")
        unit = unit_value if isinstance(unit_value, str) else None
        try:
            amount = float(credit.get("amount"))
        except (TypeError, ValueError):
            amount = None

    if unit != "USD" or amount is None:
        errors.append("Remaining account credits are unreadable or not denominated in USD")
    elif amount < minimum_credit_usd:
        errors.append("Remaining account credits are below the bounded run cost ceiling")

    return {
        "result": "PASS" if not errors else "FAIL",
        "account_plan_type": plan_type,
        "account_plan_status": plan_status,
        "remaining_credit_usd": amount,
        "minimum_credit_usd": minimum_credit_usd,
        "errors": errors,
    }


def main(arguments: list[str]) -> int:
    if len(arguments) != 4:
        print(
            "usage: verify_account_plan.py INPUT_JSON OUTPUT_JSON MINIMUM_CREDIT_USD",
            file=sys.stderr,
        )
        return 2

    try:
        payload = json.loads(Path(arguments[1]).read_text(encoding="utf-8"))
        minimum_credit_usd = float(arguments[3])
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        print(f"account-plan input is unreadable: {error}", file=sys.stderr)
        return 2

    if not isinstance(payload, dict) or minimum_credit_usd < 0:
        print(
            "account-plan input must be an object and credit floor must be non-negative",
            file=sys.stderr,
        )
        return 2

    result = verify(payload, minimum_credit_usd)
    output = Path(arguments[2])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
