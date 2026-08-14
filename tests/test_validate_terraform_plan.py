"""Tests for saved-plan safety validation."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_terraform_plan.py"
SPEC = importlib.util.spec_from_file_location("validate_terraform_plan", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def change(resource_type: str, action: str = "create", index: int = 0) -> dict[str, object]:
    return {
        "address": f"{resource_type}.proof_{index}",
        "type": resource_type,
        "change": {"actions": [action]},
    }


def bounded_apply_plan() -> dict[str, object]:
    return {
        "resource_changes": [change(resource_type) for resource_type in MODULE.REQUIRED_APPLY_TYPES]
    }


def test_bounded_create_only_plan_passes() -> None:
    result = MODULE.validate(bounded_apply_plan(), "apply")

    assert result["result"] == "PASS"


def test_apply_plan_rejects_delete_or_replace() -> None:
    plan = bounded_apply_plan()
    plan["resource_changes"][0]["change"]["actions"] = ["delete", "create"]

    result = MODULE.validate(plan, "apply")

    assert result["result"] == "FAIL"
    assert "actions" in result["errors"][0]


def test_plan_rejects_unexpected_resource_type() -> None:
    plan = bounded_apply_plan()
    plan["resource_changes"].append(change("aws_nat_gateway"))

    result = MODULE.validate(plan, "apply")

    assert result["result"] == "FAIL"
    assert "aws_nat_gateway" in result["errors"][0]


def test_plan_rejects_resource_count_above_ceiling() -> None:
    plan = bounded_apply_plan()
    plan["resource_changes"].extend(change("aws_kms_key", index=index) for index in (1, 2))

    result = MODULE.validate(plan, "apply")

    assert result["result"] == "FAIL"
    assert any("maximum" in error for error in result["errors"])


def test_empty_destroy_plan_is_safe() -> None:
    result = MODULE.validate({"resource_changes": []}, "destroy")

    assert result["result"] == "PASS"
