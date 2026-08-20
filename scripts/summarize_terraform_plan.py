"""Create a safe, reviewable inventory from a Terraform plan JSON document."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def summarize(plan: dict[str, Any], raw_bytes: bytes) -> dict[str, Any]:
    resources = []
    changes = plan.get("resource_changes", [])
    if not isinstance(changes, list):
        changes = []
    for change in changes:
        if not isinstance(change, dict):
            continue
        action = change.get("change", {})
        resources.append(
            {
                "address": change.get("address"),
                "mode": change.get("mode", "managed"),
                "type": change.get("type"),
                "actions": action.get("actions") if isinstance(action, dict) else None,
            }
        )
    resources.sort(key=lambda item: str(item["address"]))
    return {
        "format_version": plan.get("format_version"),
        "terraform_version": plan.get("terraform_version"),
        "raw_plan_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "resource_change_count": len(resources),
        "resource_changes": resources,
    }


def main(arguments: list[str]) -> int:
    if len(arguments) != 3:
        print("usage: summarize_terraform_plan.py PLAN_JSON OUTPUT_JSON", file=sys.stderr)
        return 2
    try:
        source = Path(arguments[1])
        raw = source.read_bytes()
        plan = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        print(f"Terraform plan is unreadable: {error}", file=sys.stderr)
        return 2
    if not isinstance(plan, dict):
        print("Terraform plan must be a JSON object", file=sys.stderr)
        return 2
    Path(arguments[2]).write_text(
        json.dumps(summarize(plan, raw), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
