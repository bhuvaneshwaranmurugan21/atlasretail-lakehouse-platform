"""Extract the planned AtlasRetail state-machine definition for AWS semantic validation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def resources(module: dict[str, Any]) -> list[dict[str, Any]]:
    found = list(module.get("resources", []))
    for child in module.get("child_modules", []):
        found.extend(resources(child))
    return found


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: extract_state_machine_definition.py PLAN_JSON OUTPUT_JSON")
    plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    root = plan.get("planned_values", {}).get("root_module", {})
    matches = [
        item
        for item in resources(root)
        if item.get("type") == "aws_sfn_state_machine" and item.get("name") == "retail"
    ]
    if len(matches) != 1:
        raise SystemExit(f"expected one planned AtlasRetail state machine, found {len(matches)}")
    definition = matches[0].get("values", {}).get("definition")
    if not isinstance(definition, str):
        raise SystemExit("planned state-machine definition is unknown")
    parsed = json.loads(definition)
    required = {
        "RegisterBatch",
        "StartGenerationBuild",
        "BuildIcebergGeneration",
        "ValidateGeneration",
        "PublishGeneration",
        "MarkGlueFailure",
        "GenerationFailed",
    }
    if not required <= set(parsed.get("States", {})):
        raise SystemExit("planned state machine is missing managed lifecycle states")
    Path(sys.argv[2]).write_text(
        json.dumps(parsed, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
