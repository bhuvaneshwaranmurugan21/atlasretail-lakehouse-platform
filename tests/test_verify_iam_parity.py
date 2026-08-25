from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_iam_parity.py"
SPEC = importlib.util.spec_from_file_location("verify_iam_parity", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def trust(
    subject: str | list[str] = MODULE.EXPECTED_SUBJECT,
    *,
    subject_operator: str = "StringLike",
    federated_as_list: bool = False,
) -> dict[str, object]:
    conditions: dict[str, object] = {
        "StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"},
        subject_operator: {"token.actions.githubusercontent.com:sub": subject},
    }
    if subject_operator == "StringEquals":
        conditions["StringEquals"] = {
            "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
            "token.actions.githubusercontent.com:sub": subject,
        }
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Federated": [MODULE.OIDC_PROVIDER]
                    if federated_as_list
                    else MODULE.OIDC_PROVIDER
                },
                "Action": "sts:AssumeRoleWithWebIdentity",
                "Condition": conditions,
            }
        ],
    }


def tracked_trust() -> dict[str, object]:
    return trust([MODULE.EXPECTED_SUBJECT, MODULE.EXPECTED_STABLE_ID_SUBJECT])


def test_exact_role_policy_and_main_branch_trust_pass() -> None:
    tracked = {
        "Version": "2012-10-17",
        "Statement": [{"Sid": "TrackedLabel", "Action": ["b", "a"]}],
    }
    result = MODULE.verify(
        tracked,
        tracked_trust(),
        {"Role": {"RoleName": MODULE.ROLE_NAME, "AssumeRolePolicyDocument": trust()}},
        {"PolicyNames": [MODULE.POLICY_NAME]},
        {"AttachedPolicies": []},
        {
            "RoleName": MODULE.ROLE_NAME,
            "PolicyName": MODULE.POLICY_NAME,
            "PolicyDocument": {
                "Statement": [{"Sid": "LiveLabel", "Action": ["a", "b"]}],
                "Version": "2012-10-17",
            },
        },
    )

    assert result["result"] == "PASS"
    assert result["tracked_policy_matches_live"] is True


def test_exact_string_equals_subject_is_accepted() -> None:
    tracked = {"Version": "2012-10-17", "Statement": []}
    result = MODULE.verify(
        tracked,
        tracked_trust(),
        {
            "Role": {
                "RoleName": MODULE.ROLE_NAME,
                "AssumeRolePolicyDocument": trust(
                    subject_operator="StringEquals", federated_as_list=True
                ),
            }
        },
        {"PolicyNames": [MODULE.POLICY_NAME]},
        {"AttachedPolicies": []},
        {
            "RoleName": MODULE.ROLE_NAME,
            "PolicyName": MODULE.POLICY_NAME,
            "PolicyDocument": tracked,
        },
    )

    assert result["result"] == "PASS"


def test_stable_owner_and_repository_id_subject_is_accepted() -> None:
    tracked = {"Version": "2012-10-17", "Statement": []}
    result = MODULE.verify(
        tracked,
        tracked_trust(),
        {
            "Role": {
                "RoleName": MODULE.ROLE_NAME,
                "AssumeRolePolicyDocument": trust(MODULE.EXPECTED_STABLE_ID_SUBJECT),
            }
        },
        {"PolicyNames": [MODULE.POLICY_NAME]},
        {"AttachedPolicies": []},
        {
            "RoleName": MODULE.ROLE_NAME,
            "PolicyName": MODULE.POLICY_NAME,
            "PolicyDocument": tracked,
        },
    )

    assert result["result"] == "PASS"


def test_equivalent_statement_grouping_is_accepted() -> None:
    tracked = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["service:ReadA", "service:ReadB"],
                "Resource": "arn:proof",
            }
        ],
    }
    live = {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Action": "service:ReadA", "Resource": "arn:proof"},
            {"Effect": "Allow", "Action": "service:ReadB", "Resource": "arn:proof"},
        ],
    }
    result = MODULE.verify(
        tracked,
        tracked_trust(),
        {"Role": {"RoleName": MODULE.ROLE_NAME, "AssumeRolePolicyDocument": trust()}},
        {"PolicyNames": [MODULE.POLICY_NAME]},
        {"AttachedPolicies": []},
        {
            "RoleName": MODULE.ROLE_NAME,
            "PolicyName": MODULE.POLICY_NAME,
            "PolicyDocument": live,
        },
    )

    assert result["result"] == "PASS"


def test_broad_trust_or_managed_policy_fails() -> None:
    tracked = {"Version": "2012-10-17", "Statement": []}
    result = MODULE.verify(
        tracked,
        tracked_trust(),
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
    assert result["trust_observations"][0]["subjects"] == ["repo:bhuvaneshwaranmurugan21/*"]


def test_permission_difference_is_reported_without_full_documents() -> None:
    tracked = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": "service:Required", "Resource": "arn:proof"}],
    }
    live = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": "service:Extra", "Resource": "arn:proof"}],
    }
    result = MODULE.verify(
        tracked,
        tracked_trust(),
        {"Role": {"RoleName": MODULE.ROLE_NAME, "AssumeRolePolicyDocument": trust()}},
        {"PolicyNames": [MODULE.POLICY_NAME]},
        {"AttachedPolicies": []},
        {
            "RoleName": MODULE.ROLE_NAME,
            "PolicyName": MODULE.POLICY_NAME,
            "PolicyDocument": live,
        },
    )

    assert result["missing_permission_atoms"][0]["Action"] == "service:Required"
    assert result["extra_permission_atoms"][0]["Action"] == "service:Extra"


def test_additional_broad_allow_cannot_hide_behind_a_valid_statement() -> None:
    live_trust = trust()
    live_trust["Statement"].append(trust("repo:bhuvaneshwaranmurugan21/*")["Statement"][0])
    tracked = {"Version": "2012-10-17", "Statement": []}

    result = MODULE.verify(
        tracked,
        tracked_trust(),
        {"Role": {"RoleName": MODULE.ROLE_NAME, "AssumeRolePolicyDocument": live_trust}},
        {"PolicyNames": [MODULE.POLICY_NAME]},
        {"AttachedPolicies": []},
        {
            "RoleName": MODULE.ROLE_NAME,
            "PolicyName": MODULE.POLICY_NAME,
            "PolicyDocument": tracked,
        },
    )

    assert result["result"] == "FAIL"
    assert result["trust_policy_valid"] is False


def test_non_federated_broad_principal_cannot_hide_behind_valid_statement() -> None:
    live_trust = trust()
    live_trust["Statement"].append(
        {
            "Effect": "Allow",
            "Principal": "*",
            "Action": "sts:AssumeRoleWithWebIdentity",
        }
    )
    tracked = {"Version": "2012-10-17", "Statement": []}

    result = MODULE.verify(
        tracked,
        tracked_trust(),
        {"Role": {"RoleName": MODULE.ROLE_NAME, "AssumeRolePolicyDocument": live_trust}},
        {"PolicyNames": [MODULE.POLICY_NAME]},
        {"AttachedPolicies": []},
        {
            "RoleName": MODULE.ROLE_NAME,
            "PolicyName": MODULE.POLICY_NAME,
            "PolicyDocument": tracked,
        },
    )

    assert result["result"] == "FAIL"
    assert result["trust_policy_valid"] is False
