from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "extract_state_machine_definition.py"


def test_extracts_exact_planned_lifecycle(tmp_path: Path) -> None:
    required = {
        name: {"Type": "Succeed"}
        for name in (
            "RegisterBatch",
            "StartGenerationBuild",
            "BuildIcebergGeneration",
            "ValidateGeneration",
            "PublishGeneration",
            "MarkGlueFailure",
            "GenerationFailed",
        )
    }
    plan = {
        "planned_values": {
            "root_module": {
                "resources": [
                    {
                        "type": "aws_sfn_state_machine",
                        "name": "retail",
                        "values": {"definition": json.dumps({"States": required})},
                    }
                ]
            }
        }
    }
    source = tmp_path / "plan.json"
    output = tmp_path / "definition.json"
    source.write_text(json.dumps(plan), encoding="utf-8")

    subprocess.run([sys.executable, str(SCRIPT), str(source), str(output)], check=True)

    assert set(json.loads(output.read_text())["States"]) == set(required)
