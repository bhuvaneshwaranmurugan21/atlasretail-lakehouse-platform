"""Prove that the plan-only workflow left state and tagged inventory unchanged."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

FIELDS = (
    "terraform_state_resources",
    "allowed_pending_deletion_kms_keys",
    "unexpected_resources",
)


def verify(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if before.get("result") != "PASS":
        errors.append("Pre-plan account baseline did not pass")
    if after.get("result") != "PASS":
        errors.append("Post-plan account baseline did not pass")
    changed = [field for field in FIELDS if before.get(field) != after.get(field)]
    if changed:
        errors.append(f"Persistent state or inventory changed: {changed}")
    return {
        "result": "PASS" if not errors else "FAIL",
        "persistent_inventory_unchanged": not changed,
        "compared_fields": list(FIELDS),
        "errors": errors,
    }


def main(arguments: list[str]) -> int:
    if len(arguments) != 4:
        print("usage: verify_no_change.py BEFORE_JSON AFTER_JSON OUTPUT_JSON", file=sys.stderr)
        return 2
    try:
        before = json.loads(Path(arguments[1]).read_text(encoding="utf-8"))
        after = json.loads(Path(arguments[2]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"baseline evidence is unreadable: {error}", file=sys.stderr)
        return 2
    if not isinstance(before, dict) or not isinstance(after, dict):
        print("baseline evidence must contain JSON objects", file=sys.stderr)
        return 2
    result = verify(before, after)
    Path(arguments[3]).write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
