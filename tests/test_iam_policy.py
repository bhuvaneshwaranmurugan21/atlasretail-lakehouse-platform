"""Contract tests for the bounded AtlasRetail GitHub role policy."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

POLICY_PATH = Path(__file__).parents[1] / "infra" / "iam" / "atlasretail-github-role-policy.json"
INCIDENT_OUTPUTS_PATH = (
    Path(__file__).parents[1] / "evidence" / "incidents" / "31791499897" / "terraform-outputs.json"
)
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
    account_reads = statement("ReadAccountAndTags")
    assert "freetier:GetAccountPlanState" in actions(account_reads)
    assert account_reads["Resource"] == "*"

    self_reads = statement("ReadOwnRoleConfiguration")
    assert actions(self_reads) == {
        "iam:GetRole",
        "iam:GetRolePolicy",
        "iam:ListAttachedRolePolicies",
        "iam:ListRolePolicies",
    }
    assert self_reads["Resource"].endswith(":role/AtlasRetailGitHubOidcRole")

    assert "s3:GetReplicationConfiguration" in actions(statement("StateAndLabBuckets"))

    grants = statement("AtlasKmsServiceGrants")
    assert {"kms:CreateGrant", "kms:ListGrants", "kms:RevokeGrant"} <= actions(grants)
    assert grants["Condition"] == {"Bool": {"kms:GrantIsForAWSResource": "true"}}

    global_reads = statement("GlobalProviderReads")
    assert "logs:DescribeLogGroups" in actions(global_reads)
    assert global_reads["Resource"] == "*"

    log_evidence = statement("AtlasLogsAndAlarms")
    assert "logs:FilterLogEvents" in actions(log_evidence)

    glue_resources = statement("AtlasGlue")["Resource"]
    assert (
        "arn:aws:glue:ap-south-1:887720497919:userDefinedFunction/atlasretail_*/*"
    ) in glue_resources


def test_policy_avoids_wildcard_actions_and_preserves_atlas_bounds() -> None:
    assert all("*" not in actions(item) for item in STATEMENTS)
    assert statement("AtlasRoles")["Resource"].endswith(":role/atlasretail-*")
    assert statement("AtlasLambda")["Resource"].endswith(":function:atlasretail-*")
    assert "arn:aws:s3:::atlasretail-*" in statement("StateAndLabBuckets")["Resource"]


def test_incident_manifest_preserves_names_lost_from_partial_state() -> None:
    outputs = json.loads(INCIDENT_OUTPUTS_PATH.read_text(encoding="utf-8"))
    values = {name: item["value"] for name, item in outputs.items()}

    assert values["landing_bucket"] == "atlasretail-31791499897-landing-c22831"
    assert values["warehouse_bucket"] == "atlasretail-31791499897-warehouse-c22831"
    assert values["evidence_bucket"] == "atlasretail-31791499897-evidence-c22831"
    assert values["kms_key_arn"].endswith("d44b4cc3-92b1-4adf-b6c6-fd89049671b3")
    assert all("31791499897" in value for name, value in values.items() if name != "kms_key_arn")
