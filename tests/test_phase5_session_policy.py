from __future__ import annotations

import fnmatch
import hashlib
import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "build_phase5_session_policy.py"
SPEC = importlib.util.spec_from_file_location("build_phase5_session_policy", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ROLE_POLICY = json.loads(
    (Path(__file__).parents[1] / "infra" / "iam" / "atlasretail-github-role-policy.json").read_text(
        encoding="utf-8"
    )
)


def _matches(action: str, patterns: set[str]) -> bool:
    return any(fnmatch.fnmatchcase(action.lower(), pattern.lower()) for pattern in patterns)


def _tracked_role_actions() -> set[str]:
    actions: set[str] = set()
    for statement in ROLE_POLICY["Statement"]:
        if statement["Effect"] != "Allow":
            continue
        value = statement["Action"]
        actions.update(value if isinstance(value, list) else [value])
    return actions


def _effective_actions(mode: str) -> set[str]:
    policy = MODULE.build_policy(mode)
    allows = {
        action
        for statement in policy["Statement"]
        if statement["Effect"] == "Allow"
        for action in statement["Action"]
    }
    denies = {
        action
        for statement in policy["Statement"]
        if statement["Effect"] == "Deny"
        for action in statement["Action"]
    }
    return {
        action
        for action in _tracked_role_actions()
        if _matches(action, allows) and not _matches(action, denies)
    }


def test_every_phase5_session_explicitly_denies_workload_start() -> None:
    for mode in ("plan", "deploy", "teardown"):
        policy = MODULE.build_policy(mode)
        deny = next(item for item in policy["Statement"] if item["Effect"] == "Deny")
        assert set(deny["Action"]) == set(MODULE.WORKLOAD_ACTIONS)
        assert len(MODULE.render_policy(mode)) <= MODULE.MAX_SESSION_POLICY_CHARACTERS
        assert len(MODULE.render_policy(mode)) <= MODULE.MAX_PACKED_POLICY_PLAINTEXT_BUDGET


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
    assert "glue:*" in deploy
    assert "glue:Delete*" in teardown
    assert "glue:Create*" not in teardown


def test_compact_patterns_preserve_the_exact_effective_role_intersections() -> None:
    # These digests pin the reviewed action intersections against the tracked
    # role policy. Compact patterns may change, but their effective permissions
    # cannot gain or lose an action unnoticed.
    expected = {
        "deploy": (142, "d892b5d34dd803922642fbb633f1afadd3535b8f4c934552032fae2ce778fab6"),
        "teardown": (99, "c8bbb0280b0ac54df6ed1e20260245bb0018c471ae73a79b46a5c91a4272310f"),
    }
    for mode, (count, digest) in expected.items():
        actions = sorted(_effective_actions(mode))
        actual_digest = hashlib.sha256(("\n".join(actions) + "\n").encode()).hexdigest()
        assert len(actions) == count
        assert actual_digest == digest


def test_encrypted_lease_and_service_integrations_keep_required_kms_permissions() -> None:
    deploy = _effective_actions("deploy")
    teardown = _effective_actions("teardown")
    crypto = {"kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"}

    assert crypto <= deploy
    assert crypto <= teardown
    assert {"kms:CreateGrant", "kms:RevokeGrant"} <= deploy
    assert "kms:RevokeGrant" in teardown
    assert "kms:CreateGrant" not in teardown
