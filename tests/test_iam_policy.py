"""Contract tests for the bounded AtlasRetail GitHub role policy."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

POLICY_PATH = Path(__file__).parents[1] / "infra" / "iam" / "atlasretail-github-role-policy.json"
POLICY: dict[str, Any] = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
STATEMENTS = POLICY["Statement"]


def actions(statement: dict[str, Any]) -> set[str]:
    """Normalize a policy statement's action field."""
    value = statement["Action"]
    return {value} if isinstance(value, str) else set(value)


def statement(sid: str) -> dict[str, Any]:
    """Return one policy statement by stable SID."""
    return next(item for item in STATEMENTS if item["Sid"] == sid)


def test_incident_permissions_are_present_with_required_scope() -> None:
    assert "s3:GetReplicationConfiguration" in actions(statement("StateAndLabBuckets"))

    grants = statement("AtlasKmsServiceGrants")
    assert {"kms:CreateGrant", "kms:ListGrants", "kms:RevokeGrant"} <= actions(grants)
    assert grants["Condition"] == {"Bool": {"kms:GrantIsForAWSResource": "true"}}

    global_reads = statement("GlobalProviderReads")
    assert "logs:DescribeLogGroups" in actions(global_reads)
    assert global_reads["Resource"] == "*"


def test_policy_avoids_wildcard_actions_and_preserves_atlas_bounds() -> None:
    assert all("*" not in actions(item) for item in STATEMENTS)
    assert statement("AtlasRoles")["Resource"].endswith(":role/atlasretail-*")
    assert statement("AtlasLambda")["Resource"].endswith(":function:atlasretail-*")
    assert "arn:aws:s3:::atlasretail-*" in statement("StateAndLabBuckets")["Resource"]
