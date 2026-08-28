import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "aws-bounded-lab.yml"
ARCHIVE = ROOT / "docs" / "incidents" / "legacy" / "authorizations"
AUTHORIZATION = ARCHIVE / "run-001.json"
RETRY_AUTHORIZATION = ARCHIVE / "run-002.json"
POST_RESCUE_AUTHORIZATION = ARCHIVE / "run-003.json"


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


def test_phase_two_lab_requires_explicit_manual_dispatch() -> None:
    workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    triggers = workflow["on"]

    assert set(triggers) == {"workflow_dispatch"}

    execute = workflow["jobs"]["execute"]
    assert "if" not in execute
    assert execute["env"]["ORDER_COUNT"] == "${{ inputs.order_count }}"
    assert execute["env"]["CONFIRM_DESTROY"] == "${{ inputs.confirm_destroy }}"
    assert execute["env"]["BUDGET_CEILING_USD"] == "${{ inputs.budget_ceiling_usd }}"
    scripts = "\n".join(step.get("run", "") for step in execute["steps"] if isinstance(step, dict))
    assert 'test "${CONFIRM_DESTROY}" = "DESTROY"' in scripts
    assert 'test "${ORDER_COUNT}" -le 2000' in scripts
    assert 'test "${BUDGET_CEILING_USD}" -le "${RUN_CEILING_USD}"' in scripts
    assert "python scripts/capture_account_plan.py" in scripts
    assert "python scripts/verify_account_plan.py" in scripts
    assert "freetier upgrade-account-plan" not in scripts


def test_full_scenario_chain_and_diagnostic_backfill_are_required() -> None:
    workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    execute = workflow["jobs"]["execute"]
    names = [step.get("name") for step in execute["steps"] if isinstance(step, dict)]
    expected = [
        "Execute success and replay proofs",
        "Prove failure isolation and deterministic recovery",
        "Reject temporal overlap and financial imbalance",
        "Reject an S3 version whose bytes contradict registered evidence",
        "Prove stale publisher compare-and-swap rejection",
        "Run and validate bounded Athena verification",
        "Collect AWS execution and CloudWatch evidence",
    ]
    assert [names.index(name) for name in expected] == sorted(
        names.index(name) for name in expected
    )

    collector = next(step["run"] for step in execute["steps"] if step.get("name") == expected[-1])
    assert "python scripts/backfill_execution_arns.py" in collector
    assert collector.index("backfill_execution_arns.py") < collector.index("get-execution-history")
