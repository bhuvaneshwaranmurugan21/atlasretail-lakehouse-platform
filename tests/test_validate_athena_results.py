"""Tests for exact Athena business-result evidence."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_athena_results.py"
SPEC = importlib.util.spec_from_file_location("validate_athena_results", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def athena(orders: str = "1000", gross_cents: str = "7654321") -> dict[str, object]:
    return {
        "ResultSet": {
            "Rows": [
                {"Data": [{"VarCharValue": "orders"}, {"VarCharValue": "gross_cents"}]},
                {"Data": [{"VarCharValue": orders}, {"VarCharValue": gross_cents}]},
            ]
        }
    }


def test_exact_business_result_passes() -> None:
    result = MODULE.validate({"orders": 1000, "gross_cents": 7654321}, athena())

    assert result["result"] == "PASS"
    assert result["actual"] == result["expected"]


def test_wrong_total_fails() -> None:
    result = MODULE.validate(
        {"orders": 1000, "gross_cents": 7654321}, athena(gross_cents="7654320")
    )

    assert result["result"] == "FAIL"


def test_extra_rows_fail_closed() -> None:
    response = athena()
    response["ResultSet"]["Rows"].append({"Data": [{"VarCharValue": "1"}]})

    try:
        MODULE.validate({"orders": 1000, "gross_cents": 7654321}, response)
    except ValueError as error:
        assert "one header and one data row" in str(error)
    else:
        raise AssertionError("invalid Athena result unexpectedly passed")
