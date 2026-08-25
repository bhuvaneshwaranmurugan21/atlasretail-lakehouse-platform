import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "docs" / "incidents" / "legacy"
WORKFLOW = ARCHIVE / "aws-rescue-teardown.yml"
HISTORICAL_AUTHORIZATION = ARCHIVE / "authorizations" / "rescue-31807122381.json"
AUTHORIZATION = ARCHIVE / "authorizations" / "rescue-31810378794.json"


def test_rescue_authorization_is_exactly_scoped() -> None:
    assert json.loads(HISTORICAL_AUTHORIZATION.read_text())["incident_run_id"] == 31807122381
    assert json.loads(AUTHORIZATION.read_text()) == {
        "schema_version": "1.0",
        "project": "AtlasRetail",
        "operation": "rescue-teardown",
        "incident_run_id": 31810378794,
        "incident_source_commit": "0665a4b85dc498327bd48f288fe6f430a113abf8",
        "incident_evidence_digest": (
            "sha256:763a489c96686c79b9e940e60914016609e6c054ec3d7413373856cf6cfb6f5b"
        ),
        "confirm_destroy": "DESTROY",
        "scope": "EXACT_TERRAFORM_STATE_ONLY",
    }


def test_rescue_push_trigger_and_destroy_plan_are_guarded() -> None:
    workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    triggers = workflow["on"]

    assert "workflow_dispatch" in triggers
    assert triggers["push"] == {
        "branches": ["main"],
        "paths": [".github/atlas-lab-authorizations/rescue-31810378794.json"],
    }

    rescue = workflow["jobs"]["rescue"]
    assert "Rescue Atlas run 31810378794" in rescue["if"]
    assert rescue["env"]["INCIDENT_RUN_ID"].endswith("|| '31810378794' }}")
    assert rescue["env"]["CONFIRM_DESTROY"].endswith("|| 'DESTROY' }}")

    scripts = "\n".join(step.get("run", "") for step in rescue["steps"] if isinstance(step, dict))
    assert "terraform-live-outputs-before.json" in scripts
    assert "evidence/incidents/${INCIDENT_RUN_ID}" not in scripts
    assert "terraform-destroy-plan.json" in scripts
    assert "validate_terraform_plan.py" in scripts
    assert 'terraform -chdir="${TF_DIR}" apply -auto-approve rescue.tfplan' in scripts
    assert 'test "${PUSH_BEFORE}" = "0665a4b85dc498327bd48f288fe6f430a113abf8"' in scripts


def test_legacy_rescue_workflow_is_not_executable() -> None:
    assert not (ROOT / ".github" / "workflows" / "aws-rescue-teardown.yml").exists()
