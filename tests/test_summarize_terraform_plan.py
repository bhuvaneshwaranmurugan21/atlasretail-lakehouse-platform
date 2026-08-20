from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "summarize_terraform_plan.py"
SPEC = importlib.util.spec_from_file_location("summarize_terraform_plan", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_inventory_excludes_resource_values_and_keeps_actions() -> None:
    plan = {
        "format_version": "1.2",
        "terraform_version": "1.11.4",
        "resource_changes": [
            {
                "address": "aws_s3_bucket.proof",
                "type": "aws_s3_bucket",
                "change": {"actions": ["create"], "after": {"secret": "do-not-publish"}},
            }
        ],
    }
    raw = json.dumps(plan).encode()
    result = MODULE.summarize(plan, raw)

    assert result["resource_change_count"] == 1
    assert result["resource_changes"][0]["actions"] == ["create"]
    assert "do-not-publish" not in json.dumps(result)
