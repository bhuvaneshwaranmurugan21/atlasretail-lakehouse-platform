from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "build_phase5_session_policy.py"
SPEC = importlib.util.spec_from_file_location("build_phase5_session_policy", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_every_phase5_session_explicitly_denies_workload_start() -> None:
    for mode in ("plan", "deploy", "teardown"):
        policy = MODULE.build_policy(mode)
        deny = next(item for item in policy["Statement"] if item["Effect"] == "Deny")
        assert set(deny["Action"]) == set(MODULE.WORKLOAD_ACTIONS)
        assert len(MODULE.render_policy(mode)) <= MODULE.MAX_SESSION_POLICY_CHARACTERS


def test_plan_session_does_not_allow_wildcard_or_resource_mutation() -> None:
    policy = MODULE.build_policy("plan")
    allow = next(item for item in policy["Statement"] if item["Effect"] == "Allow")

    assert allow["Action"] != "*"
    assert "glue:CreateJob" not in allow["Action"]
    assert "lambda:CreateFunction" not in allow["Action"]
    assert "states:CreateStateMachine" not in allow["Action"]
    assert "athena:CreateWorkGroup" not in allow["Action"]


def test_deploy_and_teardown_are_distinct_explicit_allowlists() -> None:
    deploy = MODULE.build_policy("deploy")["Statement"][0]["Action"]
    teardown = MODULE.build_policy("teardown")["Statement"][0]["Action"]

    assert "*" not in deploy
    assert "*" not in teardown
    assert "glue:CreateJob" in deploy
    assert "glue:DeleteJob" not in deploy
    assert "glue:DeleteJob" in teardown
    assert "glue:CreateJob" not in teardown
