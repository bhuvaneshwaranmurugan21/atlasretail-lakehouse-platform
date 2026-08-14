import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "aws-bounded-lab.yml"
AUTHORIZATION = ROOT / ".github" / "atlas-lab-authorizations" / "run-001.json"
RETRY_AUTHORIZATION = ROOT / ".github" / "atlas-lab-authorizations" / "run-002.json"
POST_RESCUE_AUTHORIZATION = ROOT / ".github" / "atlas-lab-authorizations" / "run-003.json"


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


def test_retry_authorization_is_exactly_bounded_and_auditable() -> None:
    assert json.loads(RETRY_AUTHORIZATION.read_text()) == {
        "schema_version": "1.0",
        "project": "AtlasRetail",
        "operation": "bounded-lab",
        "order_count": 1000,
        "confirm_destroy": "DESTROY",
        "authorization": "ONE_TIME",
        "budget_ceiling_usd": 5,
        "prior_guarded_run": 31806322615,
    }


def test_post_rescue_authorization_binds_cleanup_and_clean_preflight() -> None:
    assert json.loads(POST_RESCUE_AUTHORIZATION.read_text()) == {
        "schema_version": "1.0",
        "project": "AtlasRetail",
        "operation": "bounded-lab",
        "order_count": 1000,
        "confirm_destroy": "DESTROY",
        "authorization": "ONE_TIME",
        "budget_ceiling_usd": 5,
        "authorized_base_commit": "5f4634816d136dbb0a91b051b5b88eb7f2677d2a",
        "prior_failed_run": 31807122381,
        "rescue_run": 31808958248,
        "rescue_evidence_digest": (
            "sha256:93621ac080e9c49e57d521eacf084093adc010e13b65b49258ea0986f89f3887"
        ),
        "clean_preflight_run": 31809853275,
        "clean_preflight_evidence_digest": (
            "sha256:33ac289c917ef405701931b0398007dc6d42696f6a860a3cb75aa67195013744"
        ),
    }


def test_push_trigger_is_narrow_and_manual_dispatch_remains() -> None:
    workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    triggers = workflow["on"]

    assert "workflow_dispatch" in triggers
    assert triggers["push"] == {
        "branches": ["main"],
        "paths": [".github/atlas-lab-authorizations/run-003.json"],
    }

    execute = workflow["jobs"]["execute"]
    assert "Execute Atlas bounded lab after rescue: 1000 orders" in execute["if"]
    assert execute["env"]["ORDER_COUNT"].endswith("|| '1000' }}")
    assert execute["env"]["CONFIRM_DESTROY"].endswith("|| 'DESTROY' }}")
    scripts = "\n".join(step.get("run", "") for step in execute["steps"] if isinstance(step, dict))
    assert 'test "${PUSH_BEFORE}" = "5f4634816d136dbb0a91b051b5b88eb7f2677d2a"' in scripts
