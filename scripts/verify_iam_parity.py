"""Verify the live AtlasRetail OIDC role against the tracked least-privilege policy."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote

ROLE_NAME = "AtlasRetailGitHubOidcRole"
POLICY_NAME = "AtlasRetailBoundedLabPolicy"
OIDC_PROVIDER = "arn:aws:iam::887720497919:oidc-provider/token.actions.githubusercontent.com"
EXPECTED_SUBJECT = "repo:bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform:ref:refs/heads/main"


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
        equals = condition.get("StringEquals", {})
        likes = condition.get("StringLike", {})
        if not isinstance(equals, dict) or not isinstance(likes, dict):
            continue
        action = values(statement.get("Action"))
        audience = values(equals.get("token.actions.githubusercontent.com:aud"))
        subjects = values(likes.get("token.actions.githubusercontent.com:sub"))
        if (
            statement.get("Effect") == "Allow"
            and principal.get("Federated") == OIDC_PROVIDER
            and "sts:AssumeRoleWithWebIdentity" in action
            and audience == {"sts.amazonaws.com"}
            and subjects == {EXPECTED_SUBJECT}
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
        policies_match = canonical(tracked) == canonical(live)
    except (ValueError, json.JSONDecodeError):
        policies_match = False
    if not policies_match:
        errors.append("Live inline policy differs from the repository policy")

    return {
        "result": "PASS" if not errors else "FAIL",
        "role_name": ROLE_NAME,
        "inline_policy_name": POLICY_NAME,
        "trust_subject": EXPECTED_SUBJECT,
        "trust_policy_valid": trust_valid,
        "no_attached_managed_policies": attached_payload.get("AttachedPolicies") == [],
        "tracked_policy_matches_live": policies_match,
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
