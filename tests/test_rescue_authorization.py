import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "aws-rescue-teardown.yml"
AUTHORIZATION = ROOT / ".github" / "atlas-lab-authorizations" / "rescue-31807122381.json"


def test_rescue_authorization_is_exactly_scoped() -> None:
    assert json.loads(AUTHORIZATION.read_text()) == {
        "schema_version": "1.0",
        "project": "AtlasRetail",
        "operation": "rescue-teardown",
        "incident_run_id": 31807122381,
        "incident_source_commit": "a3e757bdb141b73c9394b4d4316b5786d9a677ca",
        "confirm_destroy": "DESTROY",
        "scope": "EXACT_TERRAFORM_STATE_ONLY",
    }


def test_rescue_push_trigger_and_destroy_plan_are_guarded() -> None:
    workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    triggers = workflow["on"]

    assert "workflow_dispatch" in triggers
    assert triggers["push"] == {
        "branches": ["main"],
        "paths": [".github/atlas-lab-authorizations/rescue-31807122381.json"],
    }

    rescue = workflow["jobs"]["rescue"]
    assert "Rescue Atlas run 31807122381" in rescue["if"]
    assert rescue["env"]["INCIDENT_RUN_ID"].endswith("|| '31807122381' }}")
    assert rescue["env"]["CONFIRM_DESTROY"].endswith("|| 'DESTROY' }}")

    scripts = "\n".join(step.get("run", "") for step in rescue["steps"] if isinstance(step, dict))
    assert "terraform-destroy-plan.json" in scripts
    assert "validate_terraform_plan.py" in scripts
    assert 'terraform -chdir="${TF_DIR}" apply -auto-approve rescue.tfplan' in scripts
