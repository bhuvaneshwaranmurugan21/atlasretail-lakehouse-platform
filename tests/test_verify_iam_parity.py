from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_iam_parity.py"
SPEC = importlib.util.spec_from_file_location("verify_iam_parity", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def trust(subject: str = MODULE.EXPECTED_SUBJECT) -> dict[str, object]:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Federated": MODULE.OIDC_PROVIDER},
                "Action": "sts:AssumeRoleWithWebIdentity",
                "Condition": {
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
                    },
                    "StringLike": {"token.actions.githubusercontent.com:sub": subject},
                },
            }
        ],
    }


def test_exact_role_policy_and_main_branch_trust_pass() -> None:
    tracked = {"Version": "2012-10-17", "Statement": [{"Action": ["b", "a"]}]}
    result = MODULE.verify(
        tracked,
        {"Role": {"RoleName": MODULE.ROLE_NAME, "AssumeRolePolicyDocument": trust()}},
        {"PolicyNames": [MODULE.POLICY_NAME]},
        {"AttachedPolicies": []},
        {
            "RoleName": MODULE.ROLE_NAME,
            "PolicyName": MODULE.POLICY_NAME,
            "PolicyDocument": {"Statement": [{"Action": ["a", "b"]}], "Version": "2012-10-17"},
        },
    )

    assert result["result"] == "PASS"
    assert result["tracked_policy_matches_live"] is True


def test_broad_trust_or_managed_policy_fails() -> None:
    tracked = {"Version": "2012-10-17", "Statement": []}
    result = MODULE.verify(
        tracked,
        {
            "Role": {
                "RoleName": MODULE.ROLE_NAME,
                "AssumeRolePolicyDocument": trust("repo:bhuvaneshwaranmurugan21/*"),
            }
        },
        {"PolicyNames": [MODULE.POLICY_NAME]},
        {"AttachedPolicies": [{"PolicyName": "AdministratorAccess"}]},
        {
            "RoleName": MODULE.ROLE_NAME,
            "PolicyName": MODULE.POLICY_NAME,
            "PolicyDocument": tracked,
        },
    )

    assert result["result"] == "FAIL"
    assert len(result["errors"]) == 2
