"""Guard read permissions required by Terraform provider refresh."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

POLICY_PATH = Path(__file__).parents[1] / "infra" / "iam" / "atlasretail-github-role-policy.json"


def test_provider_refresh_permissions_are_bounded() -> None:
    policy: dict[str, Any] = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    statements = {item["Sid"]: item for item in policy["Statement"]}

    bucket_actions = set(statements["StateAndLabBuckets"]["Action"])
    lambda_actions = set(statements["AtlasLambda"]["Action"])
    states_validation = statements["GlobalStepFunctionsValidation"]

    assert "s3:GetObjectTagging" in bucket_actions
    assert "lambda:ListVersionsByFunction" in lambda_actions
    assert states_validation["Action"] == "states:ValidateStateMachineDefinition"
    assert states_validation["Resource"] == "*"
    assert all("*" not in action for action in bucket_actions | lambda_actions)
