"""Verify the live AtlasRetail OIDC role against the tracked least-privilege policy."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote

TARGET = json.loads(
    (Path(__file__).resolve().parents[1] / ".github" / "atlas-target.json").read_text(
        encoding="utf-8"
    )
)
ROLE_NAME = TARGET["oidc_role_name"]
POLICY_NAME = "AtlasRetailBoundedLabPolicy"
OIDC_PROVIDER = TARGET["oidc_provider_arn"]
EXPECTED_SUBJECT = f"repo:{TARGET['repository']}:ref:{TARGET['branch_ref']}"
EXPECTED_STABLE_ID_SUBJECT = (
    "repo:bhuvaneshwaranmurugan21@276895096/"
    "atlasretail-lakehouse-platform@1333029962:ref:refs/heads/main"
)
ALLOWED_SUBJECTS = {EXPECTED_SUBJECT, EXPECTED_STABLE_ID_SUBJECT}


def load(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return value


def policy_document(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        decoded = json.loads(unquote(value))
        if isinstance(decoded, dict):
            return decoded
    raise ValueError("IAM policy document is unreadable")


def canonical(value: object) -> object:
    """Normalize IAM's order-insensitive arrays for semantic comparison."""
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        normalized = [canonical(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True))
    return value


def permission_atoms(value: dict[str, Any]) -> set[str]:
    """Flatten statement grouping into effective action/resource/condition permissions."""
    statements = value.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    atoms: set[str] = set()
    for statement in statements if isinstance(statements, list) else []:
        if not isinstance(statement, dict):
            continue
        actions = values(statement.get("Action"))
        resources = values(statement.get("Resource"))
        condition = canonical(statement.get("Condition", {}))
        for action in actions:
            for resource in resources:
                atoms.add(
                    json.dumps(
                        {
                            "Effect": statement.get("Effect"),
                            "Action": action,
                            "Resource": resource,
                            "Condition": condition,
                        },
                        sort_keys=True,
                    )
                )
    return atoms


def values(value: object) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {str(item) for item in value}
    return set()


def verify(
    tracked: dict[str, Any],
    role_payload: dict[str, Any],
    inline_payload: dict[str, Any],
    attached_payload: dict[str, Any],
    live_payload: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    trust_observations: list[dict[str, Any]] = []
    role = role_payload.get("Role", {})
    if not isinstance(role, dict) or role.get("RoleName") != ROLE_NAME:
        errors.append("Live IAM role identity does not match AtlasRetailGitHubOidcRole")

    try:
        trust = policy_document(role.get("AssumeRolePolicyDocument"))
    except (ValueError, json.JSONDecodeError):
        trust = {}
        errors.append("Live OIDC trust policy is unreadable")

    trust_valid = False
    statements = trust.get("Statement", []) if isinstance(trust, dict) else []
    if isinstance(statements, dict):
        statements = [statements]
    for statement in statements if isinstance(statements, list) else []:
        if not isinstance(statement, dict):
            continue
        principal = statement.get("Principal", {})
        condition = statement.get("Condition", {})
        if not isinstance(principal, dict) or not isinstance(condition, dict):
            continue
        audience: set[str] = set()
        subjects: set[str] = set()
        operators: set[str] = set()
        for operator, clauses in condition.items():
            if not isinstance(operator, str) or not isinstance(clauses, dict):
                continue
            if not (operator.endswith("StringEquals") or operator.endswith("StringLike")):
                continue
            operators.add(operator)
            audience |= values(clauses.get("token.actions.githubusercontent.com:aud"))
            subjects |= values(clauses.get("token.actions.githubusercontent.com:sub"))
        action = values(statement.get("Action"))
        trust_observations.append(
            {
                "effect": statement.get("Effect"),
                "federated_principals": sorted(values(principal.get("Federated"))),
                "actions": sorted(action),
                "condition_operators": sorted(operators),
                "audiences": sorted(audience),
                "subjects": sorted(subjects),
            }
        )
        if (
            statement.get("Effect") == "Allow"
            and OIDC_PROVIDER in values(principal.get("Federated"))
            and "sts:AssumeRoleWithWebIdentity" in action
            and audience == {"sts.amazonaws.com"}
            and bool(subjects)
            and subjects <= ALLOWED_SUBJECTS
        ):
            trust_valid = True
            break
    if not trust_valid:
        errors.append("OIDC trust is not restricted to the AtlasRetail main branch")

    inline_names = inline_payload.get("PolicyNames")
    if inline_names != [POLICY_NAME]:
        errors.append("AtlasRetail role must have exactly one expected inline policy")
    if attached_payload.get("AttachedPolicies") != []:
        errors.append("AtlasRetail role must not have attached managed policies")

    if live_payload.get("RoleName") != ROLE_NAME or live_payload.get("PolicyName") != POLICY_NAME:
        errors.append("Retrieved inline policy identity is unexpected")
    try:
        live = policy_document(live_payload.get("PolicyDocument"))
        tracked_atoms = permission_atoms(tracked)
        live_atoms = permission_atoms(live)
        policies_match = tracked_atoms == live_atoms
    except (ValueError, json.JSONDecodeError):
        tracked_atoms = permission_atoms(tracked)
        live_atoms = set()
        policies_match = False
    if not policies_match:
        errors.append("Live inline policy differs from the repository policy")

    return {
        "result": "PASS" if not errors else "FAIL",
        "role_name": ROLE_NAME,
        "inline_policy_name": POLICY_NAME,
        "allowed_trust_subjects": sorted(ALLOWED_SUBJECTS),
        "trust_policy_valid": trust_valid,
        "trust_observations": trust_observations,
        "no_attached_managed_policies": attached_payload.get("AttachedPolicies") == [],
        "tracked_policy_matches_live": policies_match,
        "missing_permission_atoms": [
            json.loads(item) for item in sorted(tracked_atoms - live_atoms)
        ],
        "extra_permission_atoms": [json.loads(item) for item in sorted(live_atoms - tracked_atoms)],
        "errors": errors,
    }


def main(arguments: list[str]) -> int:
    if len(arguments) != 7:
        print(
            "usage: verify_iam_parity.py TRACKED ROLE INLINE_NAMES ATTACHED LIVE OUTPUT",
            file=sys.stderr,
        )
        return 2
    try:
        result = verify(*(load(path) for path in arguments[1:6]))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"IAM parity input is unreadable: {error}", file=sys.stderr)
        return 2
    output = Path(arguments[6])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
