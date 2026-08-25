"""Fail closed unless a paid account has current local or organization-shared credit."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TARGET = json.loads(
    (Path(__file__).resolve().parents[1] / ".github" / "atlas-target.json").read_text(
        encoding="utf-8"
    )
)


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def shared_credit_amount(
    evidence: dict[str, Any] | None,
    minimum_credit_usd: float,
    now: datetime,
) -> tuple[float | None, list[str]]:
    if evidence is None:
        return None, ["No organization-shared credit evidence was supplied"]

    errors: list[str] = []
    if evidence.get("schema_version") != "1.0":
        errors.append("Organization-shared credit evidence schema is unsupported")
    if evidence.get("recipient_account_id") != TARGET["aws_account_id"]:
        errors.append("Organization-shared credit evidence targets a different AWS account")
    if evidence.get("credit_sharing_active") is not True:
        errors.append("Organization credit sharing is not attested as active")
    if evidence.get("credit_level_cost_category_restriction") is not False:
        errors.append("Organization credit-level sharing is restricted or unverified")

    try:
        amount = float(evidence.get("verified_remaining_usd"))
    except (TypeError, ValueError):
        amount = None
        errors.append("Organization-shared remaining credit is unreadable")
    if amount is not None and amount < minimum_credit_usd:
        errors.append("Organization-shared credit is below the bounded run cost ceiling")

    observed_at = parse_timestamp(evidence.get("observed_at"))
    valid_until = parse_timestamp(evidence.get("valid_until"))
    credit_expiration = parse_timestamp(
        f"{evidence.get('credit_expiration_date')}T23:59:59Z"
        if isinstance(evidence.get("credit_expiration_date"), str)
        else None
    )
    if observed_at is None or observed_at > now:
        errors.append("Organization-shared credit observation timestamp is invalid")
    if valid_until is None or now > valid_until:
        errors.append("Organization-shared credit evidence is stale")
    if credit_expiration is None or now > credit_expiration:
        errors.append("Organization-shared credit is expired or has an invalid expiration date")

    return amount, errors


def verify(
    payload: dict[str, Any],
    minimum_credit_usd: float,
    shared_credit_evidence: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate plan state and either source of the bounded run's credit floor."""
    errors: list[str] = []
    checked_at = now or datetime.now(UTC)
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

    local_credit_sufficient = unit == "USD" and amount is not None and amount >= minimum_credit_usd
    organization_credit, organization_errors = shared_credit_amount(
        shared_credit_evidence, minimum_credit_usd, checked_at
    )
    organization_credit_sufficient = not organization_errors

    credit_source = None
    if local_credit_sufficient:
        credit_source = "member-account"
    elif organization_credit_sufficient:
        credit_source = "organization-shared"
    else:
        errors.append(
            "Neither member-account nor organization-shared credit covers the run ceiling"
        )

    return {
        "result": "PASS" if not errors else "FAIL",
        "account_plan_type": plan_type,
        "account_plan_status": plan_status,
        "remaining_credit_usd": amount,
        "organization_shared_credit_usd": organization_credit,
        "credit_source": credit_source,
        "organization_credit_errors": organization_errors,
        "minimum_credit_usd": minimum_credit_usd,
        "errors": errors,
    }


def main(arguments: list[str]) -> int:
    if len(arguments) not in {4, 5}:
        print(
            "usage: verify_account_plan.py INPUT_JSON OUTPUT_JSON MINIMUM_CREDIT_USD "
            "[SHARED_CREDIT_JSON]",
            file=sys.stderr,
        )
        return 2

    try:
        payload = json.loads(Path(arguments[1]).read_text(encoding="utf-8"))
        minimum_credit_usd = float(arguments[3])
        shared_credit = (
            json.loads(Path(arguments[4]).read_text(encoding="utf-8"))
            if len(arguments) == 5
            else None
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        print(f"account-plan input is unreadable: {error}", file=sys.stderr)
        return 2

    if (
        not isinstance(payload, dict)
        or (shared_credit is not None and not isinstance(shared_credit, dict))
        or minimum_credit_usd < 0
    ):
        print(
            "account-plan input must be an object and credit floor must be non-negative",
            file=sys.stderr,
        )
        return 2

    result = verify(payload, minimum_credit_usd, shared_credit)
    output = Path(arguments[2])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
