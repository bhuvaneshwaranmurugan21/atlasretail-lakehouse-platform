"""Syntax-check every shell program embedded in an active workflow."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
EXPRESSION = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)


def _run_blocks(value: Any, location: str = "workflow") -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_location = f"{location}.{key}"
            if key == "run" and isinstance(child, str):
                result.append((child_location, child))
            else:
                result.extend(_run_blocks(child, child_location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            result.extend(_run_blocks(child, f"{location}[{index}]"))
    return result


def test_all_workflow_shell_blocks_parse_with_bash() -> None:
    failures: list[str] = []
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        for location, script in _run_blocks(workflow):
            rendered = EXPRESSION.sub("github_expression", script)
            completed = subprocess.run(
                ["bash", "-n"], input=rendered, text=True, capture_output=True, check=False
            )
            if completed.returncode != 0:
                failures.append(f"{path.relative_to(ROOT)}:{location}: {completed.stderr.strip()}")
    assert not failures, "\n".join(failures)
