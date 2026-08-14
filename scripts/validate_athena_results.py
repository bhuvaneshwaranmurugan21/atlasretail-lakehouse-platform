"""Compare a bounded Athena result with deterministic business expectations."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return parsed


def _athena_row(response: dict[str, Any]) -> dict[str, int]:
    rows = response.get("ResultSet", {}).get("Rows", [])
    if not isinstance(rows, list) or len(rows) != 2:
        raise ValueError("Athena result must contain one header and one data row")

    def values(row: object) -> list[str]:
        if not isinstance(row, dict) or not isinstance(row.get("Data"), list):
            raise ValueError("Athena row has an invalid shape")
        data: list[str] = []
        for cell in row["Data"]:
            if not isinstance(cell, dict) or "VarCharValue" not in cell:
                raise ValueError("Athena cell is missing VarCharValue")
            data.append(str(cell["VarCharValue"]))
        return data

    headers = values(rows[0])
    data = values(rows[1])
    if headers != ["orders", "gross_cents"] or len(data) != 2:
        raise ValueError("Athena result columns do not match the evidence contract")
    return {"orders": int(data[0]), "gross_cents": int(data[1])}


def validate(expected: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    """Return a machine-readable exact comparison."""
    expected_values = {
        "orders": int(expected["orders"]),
        "gross_cents": int(expected["gross_cents"]),
    }
    actual_values = _athena_row(response)
    passed = actual_values == expected_values
    return {
        "result": "PASS" if passed else "FAIL",
        "expected": expected_values,
        "actual": actual_values,
    }


def main(arguments: list[str]) -> int:
    if len(arguments) != 4:
        print(
            "usage: validate_athena_results.py EXPECTED_JSON RESULTS_JSON OUTPUT_JSON",
            file=sys.stderr,
        )
        return 2
    output = Path(arguments[3])
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = validate(_load(Path(arguments[1])), _load(Path(arguments[2])))
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        result = {"result": "FAIL", "error": str(error)}
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
