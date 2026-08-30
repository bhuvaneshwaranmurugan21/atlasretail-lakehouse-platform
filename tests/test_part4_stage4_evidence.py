"""Positive and adversarial tests for the Part 4 Stage 4 evidence boundary."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from atlasretail.part4_contract import validate_part4_contract_file
from atlasretail.part4_evidence import (
    EXPECTED_ACCOUNT,
    EXPECTED_REGION,
    EXPECTED_REPOSITORY,
    EvidenceContext,
    EvidenceError,
    build_execution_manifest,
    finalize_evidence,
    validate_execution,
)

ROOT = Path(__file__).parents[1]
POLICY_SPEC = importlib.util.spec_from_file_location(
    "part4_stage4_policy_fixture", ROOT / "scripts/build_part4_session_policy.py"
)
assert POLICY_SPEC and POLICY_SPEC.loader
POLICY = importlib.util.module_from_spec(POLICY_SPEC)
POLICY_SPEC.loader.exec_module(POLICY)
RUN_ID = "424242"
SOURCE_COMMIT = "a" * 40
TABLES = [
    "orders",
    "order_lines",
    "payments",
    "returns",
    "inventory_movements",
    "products",
]
STATUS = {
    "success": "SUCCEEDED",
    "replay": "SUCCEEDED",
    "conflict": "FAILED",
    "failure": "FAILED",
    "recovery": "SUCCEEDED",
    "temporal": "FAILED",
    "financial": "FAILED",
    "tamper": "FAILED",
}
SIGNAL = {
    "conflict": "CONFLICT:",
    "failure": "INJECTED_FAILURE",
    "temporal": "QUALITY_GATE:AMBIGUOUS_DIMENSION",
    "financial": "QUALITY_GATE:ORDER_TOTAL",
    "tamper": "QUALITY_GATE:OBJECT_IDENTITY",
}


def write(root: Path, name: str, value: object) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def change_started_manifest_version(value: dict[str, Any]) -> None:
    started = value["events"][0]["executionStartedEventDetails"]
    payload = json.loads(started["input"])
    payload["manifest_version_id"] = "substituted"
    started["input"] = json.dumps(payload)


def change_athena_actual(value: dict[str, Any]) -> None:
    value["actual"]["orders"] += 1


def change_success_glue_uri(value: dict[str, Any]) -> None:
    value["JobRuns"][0]["Arguments"]["--MANIFEST_URI"] = "s3://unrelated/manifest.json"


def history(scenario: str, glue_id: str | None = None) -> dict[str, Any]:
    batch = (
        f"success-{RUN_ID}"
        if scenario in {"success", "replay", "conflict"}
        else f"failure-{RUN_ID}"
        if scenario in {"failure", "recovery"}
        else f"{scenario}-{RUN_ID}"
    )
    registration_name = (
        "success"
        if scenario in {"success", "replay", "conflict"}
        else "failure"
        if scenario in {"failure", "recovery"}
        else "tamper_execution"
        if scenario == "tamper"
        else scenario
    )
    digest = "f" * 64 if scenario == "conflict" else "d" * 64
    events: list[dict[str, Any]] = [
        {
            "type": "ExecutionStarted",
            "executionStartedEventDetails": {
                "input": json.dumps(
                    {
                        "batch_id": batch,
                        "inject_failure": str(scenario == "failure").lower(),
                        "manifest_uri": f"s3://landing/{registration_name}/manifest.json",
                        "manifest_version_id": f"version-{registration_name}",
                        "manifest_digest": digest,
                        "source_commit": SOURCE_COMMIT,
                        "workflow_run_id": RUN_ID,
                    }
                )
            },
        }
    ]
    generation = "g-failure" if scenario in {"failure", "recovery"} else f"g-{scenario}"
    attempt = 2 if scenario == "recovery" else 1
    events.append(
        {
            "type": "TaskSucceeded",
            "taskSucceededEventDetails": {
                "resourceType": "lambda",
                "output": json.dumps(
                    {"Payload": {"generation_id": generation, "attempt": attempt}}
                ),
            },
        }
    )
    if glue_id:
        events.append(
            {
                "type": "TaskSucceeded",
                "taskSucceededEventDetails": {
                    "resourceType": "glue",
                    "output": json.dumps({"Id": glue_id}),
                },
            }
        )
    if scenario in {"success", "recovery"}:
        for state in ("VALIDATED", "PUBLISHED"):
            events.append(
                {
                    "type": "TaskSucceeded",
                    "taskSucceededEventDetails": {
                        "resourceType": "lambda",
                        "output": json.dumps(
                            {"Payload": {"status": state, "generation_id": generation}}
                        ),
                    },
                }
            )
    terminal = "ExecutionSucceeded" if STATUS[scenario] == "SUCCEEDED" else "ExecutionFailed"
    event: dict[str, Any] = {"type": terminal}
    if scenario in SIGNAL:
        event["executionFailedEventDetails"] = {"cause": SIGNAL[scenario]}
    events.append(event)
    return {"events": events}


def glue_run(scenario: str, state: str, inject: bool, generation: str) -> dict[str, Any]:
    batch = f"failure-{RUN_ID}" if scenario in {"failure", "recovery"} else f"{scenario}-{RUN_ID}"
    registration_name = (
        "failure"
        if scenario in {"failure", "recovery"}
        else "tamper_execution"
        if scenario == "tamper"
        else scenario
    )
    return {
        "Id": f"jr-{scenario}",
        "JobRunState": state,
        "WorkerType": "G.1X",
        "NumberOfWorkers": 2,
        "GlueVersion": "5.0",
        "DPUSeconds": 10,
        "Arguments": {
            "--BATCH_ID": batch,
            "--GENERATION_ID": generation,
            "--MANIFEST_URI": f"s3://landing/{registration_name}/manifest.json",
            "--MANIFEST_VERSION_ID": f"version-{registration_name}",
            "--MANIFEST_DIGEST": "d" * 64,
            "--INJECT_FAILURE": str(inject).lower(),
        },
    }


def complete_evidence(root: Path) -> EvidenceContext:
    contract = validate_part4_contract_file(ROOT / "contracts/part4/run-contract.json")
    target_sha = hashlib.sha256((ROOT / ".github/atlas-target.json").read_bytes()).hexdigest()
    write(
        root,
        "admission-receipt.json",
        {
            "result": "PASS",
            "workflow": {
                "repository": EXPECTED_REPOSITORY,
                "run_id": RUN_ID,
                "run_attempt": "1",
                "source_commit": SOURCE_COMMIT,
            },
            "bindings": {
                "contract_sha256": contract.contract_sha256,
                "target_sha256": target_sha,
                "aws_account_id": EXPECTED_ACCOUNT,
                "aws_region": EXPECTED_REGION,
            },
            "prerequisites": {"receipt_sha256": "e" * 64},
        },
    )
    for name in (
        "source-provenance-validation.json",
        "preflight.json",
        "deployment-verification.json",
    ):
        write(root, name, {"result": "PASS"})
    write(root, "terraform-apply-plan-validation.json", {"result": "PASS", "mode": "apply"})
    write(root, "execution-session-policy.json", POLICY.build_policy("execution"))
    execution_policy_sha = hashlib.sha256(
        (root / "execution-session-policy.json").read_bytes()
    ).hexdigest()
    write(
        root,
        "execution-session-receipt.json",
        {
            "result": "PASS",
            "aws_account_id": EXPECTED_ACCOUNT,
            "aws_region": EXPECTED_REGION,
            "session_policy_sha256": execution_policy_sha,
        },
    )
    owner = f"{EXPECTED_REPOSITORY}/{RUN_ID}/1"
    write(root, "lease-acquisition.json", {"result": "PASS", "owner": owner})
    write(
        root,
        "teardown-authority.json",
        {
            "authority_version": "1.0",
            "workflow": {
                "repository": EXPECTED_REPOSITORY,
                "run_id": RUN_ID,
                "run_attempt": "1",
                "source_commit": SOURCE_COMMIT,
            },
            "lease": {"owner": owner},
        },
    )
    authority_sha = hashlib.sha256((root / "teardown-authority.json").read_bytes()).hexdigest()
    write(
        root,
        "teardown-authority-digest.json",
        {"result": "PASS", "authority_sha256": authority_sha},
    )
    write(
        root,
        "teardown-authority-verification.json",
        {
            "result": "PASS",
            "run_id": RUN_ID,
            "run_attempt": "1",
            "source_commit": SOURCE_COMMIT,
            "lease_owner": owner,
            "authority_file_sha256": authority_sha,
            "managed_address_count": 40,
            "read_only_data_address_count": 6,
            "plan_files_revalidated": True,
            "authority_bound_recovery_mode": False,
        },
    )
    write(
        root,
        "lease-authority-binding.json",
        {
            "result": "PASS",
            "owner": owner,
            "run_attempt": "1",
            "source_commit": SOURCE_COMMIT,
            "state": "AUTHORITY_BOUND",
            "consistent_read": True,
            "authority_sha256": authority_sha,
        },
    )
    write(
        root,
        "apply-outcome.json",
        {
            "result": "PASS",
            "exit_code": 0,
            "saved_plan_only": True,
            "authority_sha256": authority_sha,
            "started_at": "2026-08-30T00:00:00+00:00",
            "finished_at": "2026-08-30T00:01:00+00:00",
        },
    )
    write(
        root,
        "budget-verification.json",
        {"result": "PASS", "planned_gross_cost_ceiling_usd": 5},
    )
    for scenario in ("success", "failure", "tamper", "temporal", "financial"):
        write(
            root,
            f"{scenario}-registration.json",
            {
                "manifest_uri": f"s3://landing/{scenario}/manifest.json",
                "manifest_version_id": f"version-{scenario}",
                "identity_digest": "d" * 64,
            },
        )
    write(
        root,
        "tamper-execution-registration.json",
        {
            "manifest_uri": "s3://landing/tamper_execution/manifest.json",
            "manifest_version_id": "version-tamper_execution",
            "identity_digest": "d" * 64,
        },
    )
    write(root, "tamper-mutation.json", {"result": "DECLARED"})
    glue_ids = {
        "success": "jr-success",
        "failure": "jr-failure",
        "recovery": "jr-recovery",
        "temporal": "jr-temporal",
        "financial": "jr-financial",
        "tamper": "jr-tamper",
    }
    executions = []
    for scenario, status in STATUS.items():
        executions.append(
            {
                "name": f"{scenario}-{RUN_ID}",
                "status": status,
                "executionArn": (
                    f"arn:aws:states:{EXPECTED_REGION}:{EXPECTED_ACCOUNT}:execution:"
                    f"atlasretail-{RUN_ID}-pipeline:{scenario}-{RUN_ID}"
                ),
            }
        )
        write(root, f"{scenario}-history.json", history(scenario, glue_ids.get(scenario)))
    write(root, "stepfunctions-executions.json", {"executions": executions})
    write(
        root,
        "glue-job-runs.json",
        {
            "JobRuns": [
                glue_run("success", "SUCCEEDED", False, "g-success"),
                glue_run("failure", "FAILED", True, "g-failure"),
                glue_run("recovery", "SUCCEEDED", False, "g-failure"),
                glue_run("temporal", "FAILED", False, "g-temporal"),
                glue_run("financial", "FAILED", False, "g-financial"),
                glue_run("tamper", "FAILED", False, "g-tamper"),
            ]
        },
    )
    success_pointer = {
        "Item": {
            "active_generation": {"S": "g-success"},
            "pointer_version": {"N": "1"},
        }
    }
    recovery_pointer = {
        "Item": {
            "active_generation": {"S": "g-failure"},
            "pointer_version": {"N": "2"},
        }
    }
    for name in (
        "pointer-after-success.json",
        "pointer-after-replay.json",
        "pointer-after-conflict.json",
        "pointer-before-failure.json",
        "pointer-after-failure.json",
    ):
        write(root, name, success_pointer)
    for name in (
        "pointer-after-recovery.json",
        "pointer-before-temporal.json",
        "pointer-after-temporal.json",
        "pointer-before-financial.json",
        "pointer-after-financial.json",
        "pointer-after-tamper.json",
    ):
        write(root, name, recovery_pointer)
    winner = {"status": "RESOLVED", "generation_id": "g-failure", "pointer_version": 2}
    write(
        root,
        "stale-publisher/summary.json",
        {
            "result": "PASS",
            "error": "STALE_PUBLISHER: expected 0",
            "winner_before": winner,
            "winner_after": winner,
        },
    )
    write(root, "serving-resolution.json", winner)
    query_prefix = {
        "Status": {"State": "SUCCEEDED"},
        "Statistics": {"DataScannedInBytes": 1024},
        "WorkGroup": f"atlasretail-{RUN_ID}-verification",
    }
    write(
        root,
        "athena-orders.json",
        {"QueryExecution": {**query_prefix, "QueryExecutionId": "q-orders", "Query": "g-failure"}},
    )
    write(
        root,
        "athena-six-table-serving.json",
        {
            "QueryExecution": {
                **query_prefix,
                "QueryExecutionId": "q-six",
                "Query": " UNION ALL ".join(["g-failure"] * 6),
            }
        },
    )
    expected_result = {"orders": 500, "gross_cents": 4_595_276}
    write(root, "failure-expected-results.json", expected_result)
    write(
        root,
        "athena-validation.json",
        {"result": "PASS", "expected": expected_result, "actual": expected_result},
    )
    write(
        root,
        "athena-orders-results.json",
        {
            "ResultSet": {
                "Rows": [
                    {
                        "Data": [
                            {"VarCharValue": "orders"},
                            {"VarCharValue": "gross_cents"},
                        ]
                    },
                    {
                        "Data": [
                            {"VarCharValue": "500"},
                            {"VarCharValue": "4595276"},
                        ]
                    },
                ]
            }
        },
    )
    write(
        root,
        "athena-six-table-serving-results.json",
        {
            "ResultSet": {
                "Rows": [
                    {"Data": [{"VarCharValue": name} for name in TABLES]},
                    {"Data": [{"VarCharValue": "1"} for _ in TABLES]},
                ]
            }
        },
    )
    sources = {}
    for source in ("glue", "states", "lambda"):
        write(root, f"{source}-cloudwatch-events.json", {"events": [{"message": source}]})
        sources[source] = {
            "event_count": 1,
            "log_group": f"/aws/{source}/atlasretail-{RUN_ID}",
        }
    write(
        root,
        "cloudwatch-export-receipt.json",
        {"result": "PASS", "pagination_complete": True, "sources": sources},
    )
    return EvidenceContext(root, ROOT, SOURCE_COMMIT, RUN_ID, "1", 5)


def complete_final_evidence(root: Path) -> EvidenceContext:
    context = complete_evidence(root)
    checkpoint = validate_execution(context)
    write(root, "execution-evidence-manifest.json", build_execution_manifest(root))
    write(root, "execution-checkpoint.json", checkpoint)
    write(root, "terraform-destroy-plan-validation.json", {"result": "PASS", "mode": "destroy"})
    write(root, "teardown.json", {"result": "PASS", "checks": [{"deleted": True}]})
    write(root, "teardown-session-policy.json", POLICY.build_policy("teardown"))
    owner = f"{EXPECTED_REPOSITORY}/{RUN_ID}/1"
    authority_sha = hashlib.sha256((root / "teardown-authority.json").read_bytes()).hexdigest()
    write(
        root,
        "teardown-authority-recovery-verification.json",
        {
            "result": "PASS",
            "run_id": RUN_ID,
            "run_attempt": "1",
            "source_commit": SOURCE_COMMIT,
            "lease_owner": owner,
            "authority_file_sha256": authority_sha,
            "managed_address_count": 40,
            "read_only_data_address_count": 6,
            "plan_files_revalidated": False,
            "authority_bound_recovery_mode": True,
        },
    )
    write(
        root,
        "teardown-lease-authority-verification.json",
        {
            "result": "PASS",
            "owner": owner,
            "run_attempt": "1",
            "source_commit": SOURCE_COMMIT,
            "state": "AUTHORITY_BOUND",
            "consistent_read": True,
            "authority_sha256": authority_sha,
        },
    )
    teardown_policy_sha = hashlib.sha256(
        (root / "teardown-session-policy.json").read_bytes()
    ).hexdigest()
    write(
        root,
        "teardown-session-receipt.json",
        {
            "result": "PASS",
            "aws_account_id": EXPECTED_ACCOUNT,
            "aws_region": EXPECTED_REGION,
            "session_policy_sha256": teardown_policy_sha,
        },
    )
    write(
        root,
        "lease-release-verification.json",
        {
            "result": "PASS",
            "owner": owner,
            "run_attempt": "1",
            "source_commit": SOURCE_COMMIT,
            "authority_sha256": authority_sha,
            "lease_absent": True,
            "consistent_read": True,
        },
    )
    write(
        root,
        "post-teardown-budget-verification.json",
        {"result": "PASS", "planned_gross_cost_ceiling_usd": 5},
    )
    write(
        root,
        "final-runtime-provenance.json",
        {
            "result": "PASS",
            "terraform_version": "1.11.4",
            "execution_started_at": "2026-08-30T00:00:00+00:00",
            "execution_finished_at": "2026-08-30T00:10:00+00:00",
        },
    )
    write(root, "terraform-apply-plan.json", {"plan": "apply"})
    write(root, "terraform-destroy-plan.json", {"plan": "destroy"})
    write(
        root,
        "terraform-destroy-plan-digests.json",
        {
            "schema_version": "1.0",
            "proof": "part4-saved-destroy-plan-digests",
            "result": "PASS",
            "binary_sha256": "f" * 64,
            "json_sha256": hashlib.sha256(
                (root / "terraform-destroy-plan.json").read_bytes()
            ).hexdigest(),
            "validation_sha256": hashlib.sha256(
                (root / "terraform-destroy-plan-validation.json").read_bytes()
            ).hexdigest(),
        },
    )
    return context


def test_checkpoint_is_complete_but_never_aws_verified(tmp_path: Path) -> None:
    result = validate_execution(complete_evidence(tmp_path))

    assert result["result"] == "PASS"
    assert result["claim_level"] == "UNCLAIMED"
    assert result["execution_state"] == "AWS_EXECUTION_VALIDATED_PENDING_TEARDOWN"
    assert result["teardown_complete"] is False
    assert len(result["domains"]) == 16


def test_finalizer_requires_all_twenty_domains(tmp_path: Path) -> None:
    result = finalize_evidence(complete_final_evidence(tmp_path))

    assert result["result"] == "PASS"
    assert result["claim_level"] == "AWS_VERIFIED"
    assert result["production_claim"] is False
    assert len(result["domains"]) == 20


def test_destroy_plan_json_tamper_breaks_saved_binary_binding(tmp_path: Path) -> None:
    context = complete_final_evidence(tmp_path)
    write(tmp_path, "terraform-destroy-plan.json", {"plan": "substituted"})
    with pytest.raises(EvidenceError, match="destroy plan JSON digest differs"):
        finalize_evidence(context)


@pytest.mark.parametrize(
    ("file_name", "mutation", "message"),
    [
        (
            "conflict-history.json",
            lambda value: value["events"][-1].update(
                {"executionFailedEventDetails": {"cause": "wrong"}}
            ),
            "required failure signal",
        ),
        (
            "replay-history.json",
            lambda value: value["events"].insert(1, history("success", "jr-extra")["events"][2]),
            "replay started",
        ),
        (
            "pointer-after-failure.json",
            lambda value: value["Item"].update({"active_generation": {"S": "changed"}}),
            "active pointer",
        ),
        (
            "stale-publisher/summary.json",
            lambda value: value.update({"winner_after": {"generation_id": "changed"}}),
            "changed winner",
        ),
        (
            "athena-six-table-serving.json",
            lambda value: value["QueryExecution"].update({"Query": "g-failure"}),
            "not pinned",
        ),
        (
            "cloudwatch-export-receipt.json",
            lambda value: value["sources"]["glue"].update({"log_group": "/aws/glue/unrelated"}),
            "not run-bound",
        ),
        (
            "budget-verification.json",
            lambda value: value.update({"planned_gross_cost_ceiling_usd": 6}),
            "budget ceiling",
        ),
        (
            "replay-history.json",
            change_started_manifest_version,
            "manifest version differs from registration",
        ),
        (
            "glue-job-runs.json",
            change_success_glue_uri,
            "differs from execution input manifest_uri",
        ),
        (
            "athena-validation.json",
            change_athena_actual,
            "differs from runtime expected results",
        ),
        (
            "apply-outcome.json",
            lambda value: value.update({"authority_sha256": "b" * 64}),
            "saved apply outcome",
        ),
        (
            "lease-authority-binding.json",
            lambda value: value.update({"source_commit": "b" * 40}),
            "lease was not bound",
        ),
        (
            "teardown-authority-verification.json",
            lambda value: value.update({"plan_files_revalidated": False}),
            "teardown authority was not independently validated",
        ),
    ],
)
def test_execution_mutations_fail_closed(
    tmp_path: Path, file_name: str, mutation: Any, message: str
) -> None:
    context = complete_evidence(tmp_path)
    path = tmp_path / file_name
    value = json.loads(path.read_text(encoding="utf-8"))
    mutation(value)
    write(tmp_path, file_name, value)

    with pytest.raises(EvidenceError, match=message):
        validate_execution(context)


def test_duplicate_execution_fails_closed(tmp_path: Path) -> None:
    context = complete_evidence(tmp_path)
    path = tmp_path / "stepfunctions-executions.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["executions"].append(copy.deepcopy(value["executions"][0]))
    write(tmp_path, path.name, value)

    with pytest.raises(EvidenceError, match="exactly the eight"):
        validate_execution(context)


def test_metered_estimate_above_admitted_ceiling_fails_closed(tmp_path: Path) -> None:
    context = complete_evidence(tmp_path)
    path = tmp_path / "glue-job-runs.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    for run in value["JobRuns"]:
        run["DPUSeconds"] = 100_000
    write(tmp_path, path.name, value)

    with pytest.raises(EvidenceError, match="exceeds admitted budget ceiling"):
        validate_execution(context)


@pytest.mark.parametrize(
    ("file_name", "mutation", "message"),
    [
        (
            "terraform-destroy-plan-validation.json",
            lambda value: value.update({"mode": "apply"}),
            "mode is not destroy",
        ),
        ("teardown.json", lambda value: value["checks"][0].update({"deleted": False}), "residue"),
        (
            "lease-release-verification.json",
            lambda value: value.update({"authority_sha256": "b" * 64}),
            "exact immutable authority",
        ),
        (
            "lease-release-verification.json",
            lambda value: value.update({"lease_absent": False}),
            "absence",
        ),
        (
            "teardown-authority-recovery-verification.json",
            lambda value: value.update({"run_attempt": "2"}),
            "recover exact immutable authority",
        ),
        (
            "post-teardown-budget-verification.json",
            lambda value: value.update({"planned_gross_cost_ceiling_usd": 4}),
            "budget ceiling",
        ),
        (
            "final-runtime-provenance.json",
            lambda value: value.update({"execution_finished_at": "2026-08-29T23:59:00+00:00"}),
            "timezone-aware and monotonic",
        ),
    ],
)
def test_final_mutations_cannot_issue_aws_verified(
    tmp_path: Path, file_name: str, mutation: Any, message: str
) -> None:
    context = complete_final_evidence(tmp_path)
    path = tmp_path / file_name
    value = json.loads(path.read_text(encoding="utf-8"))
    mutation(value)
    write(tmp_path, file_name, value)

    with pytest.raises(EvidenceError, match=message):
        finalize_evidence(context)


def test_premature_aws_verified_checkpoint_is_rejected(tmp_path: Path) -> None:
    context = complete_final_evidence(tmp_path)
    checkpoint = json.loads((tmp_path / "execution-checkpoint.json").read_text())
    checkpoint["claim_level"] = "AWS_VERIFIED"
    write(tmp_path, "execution-checkpoint.json", checkpoint)

    with pytest.raises(EvidenceError, match="invalid final claim"):
        finalize_evidence(context)


def test_post_checkpoint_evidence_mutation_is_rejected(tmp_path: Path) -> None:
    context = complete_final_evidence(tmp_path)
    write(tmp_path, "lambda-cloudwatch-events.json", {"events": [{"message": "changed"}]})

    with pytest.raises(EvidenceError, match="changed after checkpoint"):
        finalize_evidence(context)
