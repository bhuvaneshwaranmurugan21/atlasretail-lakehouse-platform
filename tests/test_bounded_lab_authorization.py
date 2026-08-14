import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "aws-bounded-lab.yml"
AUTHORIZATION = (
    ROOT / ".github" / "atlas-lab-authorizations" / "run-001.json"
)


def test_one_time_authorization_is_exactly_bounded() -> None:
    assert json.loads(AUTHORIZATION.read_text()) == {
        "schema_version": "1.0",
        "project": "AtlasRetail",
        "operation": "bounded-lab",
        "order_count": 1000,
        "confirm_destroy": "DESTROY",
        "authorization": "ONE_TIME",
        "budget_ceiling_usd": 5,
    }


def test_push_trigger_is_narrow_and_manual_dispatch_remains() -> None:
    workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    triggers = workflow["on"]

    assert "workflow_dispatch" in triggers
    assert triggers["push"] == {
        "branches": ["main"],
        "paths": [".github/atlas-lab-authorizations/run-001.json"],
    }

    execute = workflow["jobs"]["execute"]
    assert "Authorize Atlas bounded lab: 1000 orders" in execute["if"]
    assert execute["env"]["ORDER_COUNT"].endswith("|| '1000' }}")
    assert execute["env"]["CONFIRM_DESTROY"].endswith("|| 'DESTROY' }}")
