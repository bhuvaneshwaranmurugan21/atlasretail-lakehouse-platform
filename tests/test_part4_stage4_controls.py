"""Static safety checks for the Stage 4 session and workflow boundaries."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/build_part4_session_policy.py"
SPEC = importlib.util.spec_from_file_location("build_part4_session_policy", SCRIPT)
assert SPEC and SPEC.loader
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)


def test_session_policies_are_compact_and_region_bound() -> None:
    execution = POLICY.render_policy("execution")
    teardown = POLICY.render_policy("teardown")

    assert len(execution) <= POLICY.MAX_PACKED_RISK
    assert len(teardown) <= POLICY.MAX_PACKED_RISK
    forbidden_region = "ap-" + "south-1"
    assert "ap-southeast-2" in execution and forbidden_region not in execution
    assert "ap-southeast-2" in teardown and forbidden_region not in teardown
    execution_denies = json.loads(execution)["Statement"][-1]["Action"]
    teardown_denies = json.loads(teardown)["Statement"][-1]["Action"]
    assert "states:StartExecution" not in execution_denies
    assert "states:StartExecution" in teardown_denies
    assert "dynamodb:CreateTable" in teardown_denies
    assert "lambda:Update*" in teardown_denies


def test_workflow_orders_verification_checkpoint_and_finality() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/aws-bounded-lab.yml").read_text())
    execute = [step.get("name", step.get("uses")) for step in workflow["jobs"]["execute"]["steps"]]
    teardown = [
        step.get("name", step.get("uses")) for step in workflow["jobs"]["teardown"]["steps"]
    ]

    assert execute.index("Verify the deployed control plane before any workload") < execute.index(
        "Upload only the admitted immutable inputs"
    )
    assert execute.index("Collect AWS execution and CloudWatch evidence") < execute.index(
        "Persist evidence before teardown"
    )
    assert teardown.index("Prove teardown across AWS and Terraform inventories") < teardown.index(
        "Release only a verified clean run's account-wide lease"
    )
    assert teardown.index(
        "Release only a verified clean run's account-wide lease"
    ) < teardown.index("Finalize only complete execution and teardown evidence")


def test_legacy_pre_teardown_summarizer_always_fails(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/summarize_aws_evidence.py"),
            str(tmp_path),
            "a" * 40,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    summary = json.loads((tmp_path / "summary.json").read_text())

    assert completed.returncode == 1
    assert summary["result"] == "FAIL"
    assert summary["claim_level"] == "UNCLAIMED"
