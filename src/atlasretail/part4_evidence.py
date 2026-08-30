"""Fail-closed semantic validation for AtlasRetail Part 4 AWS evidence.

The execution checkpoint deliberately cannot emit ``AWS_VERIFIED``.  That
claim is available only to :func:`finalize_evidence`, after destroy, AWS and
Terraform inventory, budget, and account-lease finality all pass.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from atlasretail.part4_contract import (
    CONTRACT_RELATIVE_PATH,
    EXPECTED_SCENARIOS,
    REQUIRED_EVIDENCE_DOMAINS,
    REQUIRED_PROVENANCE_FIELDS,
    TARGET_RELATIVE_PATH,
    validate_part4_contract_file,
)

EXECUTION_DOMAINS = REQUIRED_EVIDENCE_DOMAINS - {
    "saved_destroy_plan",
    "post_teardown_inventories",
    "lease_release",
    "final_summary",
}
HISTORY_SCENARIOS = tuple(
    name for name, value in EXPECTED_SCENARIOS.items() if value["step_functions_execution"]
)
GLUE_SCENARIOS = tuple(name for name, value in EXPECTED_SCENARIOS.items() if value["glue_job_run"])
EXPECTED_ACCOUNT = "857229544428"
EXPECTED_REGION = "ap-southeast-2"
EXPECTED_REPOSITORY = "bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform"


class EvidenceError(ValueError):
    """Raised when required evidence is absent, inconsistent, or ambiguous."""


@dataclass(frozen=True)
class EvidenceContext:
    root: Path
    repo_root: Path
    source_commit: str
    run_id: str
    run_attempt: str
    budget_ceiling_usd: float


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvidenceError(f"{path.name}: unreadable JSON: {error}") from error


def _object(path: Path) -> dict[str, Any]:
    value = _load(path)
    if not isinstance(value, dict):
        raise EvidenceError(f"{path.name}: expected JSON object")
    return value


def _pass(path: Path, *, mode: str | None = None) -> dict[str, Any]:
    value = _object(path)
    if value.get("result") != "PASS":
        raise EvidenceError(f"{path.name}: result is not PASS")
    if mode is not None and value.get("mode") != mode:
        raise EvidenceError(f"{path.name}: mode is not {mode}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def build_execution_manifest(root: Path) -> dict[str, str]:
    """Digest immutable pre-teardown files without self-referential outputs."""
    excluded = {
        "execution-checkpoint.json",
        "execution-evidence-manifest.json",
        "final-summary.json",
        "evidence-manifest.json",
    }
    return {
        str(path.relative_to(root)): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name not in excluded
    }


def canonical_manifest_sha256(manifest: dict[str, str]) -> str:
    """Return the canonical digest used in the checkpoint."""
    return _canonical_sha256(manifest)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def _flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise EvidenceError(f"invalid boolean flag {value!r}")


def _history_text(history: dict[str, Any]) -> str:
    return json.dumps(history, sort_keys=True, separators=(",", ":"))


def _walk_json(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk_json(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_json(nested)
    elif isinstance(value, str) and value[:1] in {"{", "["}:
        try:
            nested = json.loads(value)
        except json.JSONDecodeError:
            return
        yield from _walk_json(nested)


def _started_input(history: dict[str, Any]) -> dict[str, Any]:
    for event in history.get("events", []):
        if not isinstance(event, dict):
            continue
        detail = event.get("executionStartedEventDetails")
        if not isinstance(detail, dict):
            continue
        raw = detail.get("input")
        if isinstance(raw, str):
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as error:
                raise EvidenceError("execution history has invalid started input") from error
            if isinstance(value, dict):
                return value
    raise EvidenceError("execution history has no executionStarted input")


def _status_from_history(history: dict[str, Any]) -> str:
    types = {event.get("type") for event in history.get("events", []) if isinstance(event, dict)}
    if "ExecutionSucceeded" in types:
        return "SUCCEEDED"
    if "ExecutionFailed" in types:
        return "FAILED"
    raise EvidenceError("execution history has no terminal event")


def _glue_ids(history: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    for event in history.get("events", []):
        if not isinstance(event, dict):
            continue
        detail = event.get("taskSucceededEventDetails") or event.get("taskFailedEventDetails")
        if not isinstance(detail, dict) or detail.get("resourceType") != "glue":
            continue
        for value in _walk_json(detail.get("output", detail.get("cause", {}))):
            job_run_id = value.get("Id") or value.get("JobRunId") or value.get("jobRunId")
            if isinstance(job_run_id, str) and job_run_id:
                found.add(job_run_id)
    return found


def _values(history: dict[str, Any], key: str) -> list[Any]:
    return [value[key] for value in _walk_json(history) if key in value]


def _validate_provenance(context: EvidenceContext) -> dict[str, Any]:
    contract = validate_part4_contract_file(
        context.repo_root / CONTRACT_RELATIVE_PATH, repo_root=context.repo_root
    )
    target_sha = _sha256(context.repo_root / TARGET_RELATIVE_PATH)
    receipt = _pass(context.root / "admission-receipt.json")
    required = {
        "repository": EXPECTED_REPOSITORY,
        "workflow_run_id": context.run_id,
        "workflow_attempt": context.run_attempt,
        "source_commit": context.source_commit,
        "contract_sha256": contract.contract_sha256,
        "target_sha256": target_sha,
        "aws_account_id": EXPECTED_ACCOUNT,
        "aws_region": EXPECTED_REGION,
    }
    workflow = receipt.get("workflow", {})
    bindings = receipt.get("bindings", {})
    for key, expected in required.items():
        observed = (
            workflow.get(key)
            if key in {"repository", "workflow_run_id", "workflow_attempt", "source_commit"}
            else bindings.get(key)
        )
        if key == "workflow_run_id":
            observed = workflow.get("run_id")
        elif key == "workflow_attempt":
            observed = workflow.get("run_attempt")
        _require(str(observed) == str(expected), f"admission-receipt.json: wrong {key}")
    return {
        **required,
        "workflow_name": "AWS bounded lab",
        "contract_version": "1.0.0",
        "oidc_role_arn": f"arn:aws:iam::{EXPECTED_ACCOUNT}:role/AtlasRetailGitHubOidcRole",
    }


def _validate_executions(
    context: EvidenceContext,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    inventory = _object(context.root / "stepfunctions-executions.json").get("executions")
    if not isinstance(inventory, list):
        raise EvidenceError("stepfunctions execution inventory is missing")
    expected_names = {f"{name}-{context.run_id}" for name in HISTORY_SCENARIOS}
    selected = [
        row for row in inventory if isinstance(row, dict) and row.get("name") in expected_names
    ]
    names = [str(row.get("name")) for row in selected]
    _require(
        len(selected) == 8 and set(names) == expected_names and len(set(names)) == 8,
        "Step Functions inventory must contain exactly the eight run-bound executions",
    )

    histories: dict[str, dict[str, Any]] = {}
    for scenario in HISTORY_SCENARIOS:
        expected = EXPECTED_SCENARIOS[scenario]
        row = next(value for value in selected if value["name"] == f"{scenario}-{context.run_id}")
        _require(
            row.get("status") == expected["expected_result"], f"{scenario}: wrong inventory status"
        )
        arn = str(row.get("executionArn", ""))
        arn_prefix = (
            f"arn:aws:states:{EXPECTED_REGION}:{EXPECTED_ACCOUNT}:execution:"
            f"atlasretail-{context.run_id}-pipeline:"
        )
        _require(
            arn == arn_prefix + f"{scenario}-{context.run_id}", f"{scenario}: wrong execution ARN"
        )
        history = _object(context.root / f"{scenario}-history.json")
        _require(
            _status_from_history(history) == expected["expected_result"],
            f"{scenario}: wrong terminal history",
        )
        started = _started_input(history)
        _require(
            str(started.get("workflow_run_id")) == context.run_id,
            f"{scenario}: wrong workflow_run_id",
        )
        _require(
            started.get("source_commit") == context.source_commit,
            f"{scenario}: wrong source_commit",
        )
        expected_batch = (
            f"success-{context.run_id}"
            if scenario in {"success", "replay", "conflict"}
            else f"failure-{context.run_id}"
            if scenario in {"failure", "recovery"}
            else f"{scenario}-{context.run_id}"
        )
        _require(started.get("batch_id") == expected_batch, f"{scenario}: wrong batch identity")
        _require(
            _flag(started.get("inject_failure")) == (scenario == "failure"),
            f"{scenario}: wrong injection flag",
        )
        signal = expected["failure_signal"]
        if signal:
            _require(
                str(signal) in _history_text(history), f"{scenario}: required failure signal absent"
            )
        histories[scenario] = history
    for scenario in ("success", "recovery"):
        statuses = set(_values(histories[scenario], "status"))
        _require(
            {"VALIDATED", "PUBLISHED"} <= statuses,
            f"{scenario}: validation-before-publication proof is incomplete",
        )
    failure_generations = set(_values(histories["failure"], "generation_id"))
    recovery_generations = set(_values(histories["recovery"], "generation_id"))
    _require(
        bool(failure_generations & recovery_generations),
        "failure and recovery do not share a generation identity",
    )
    failure_attempts = [
        value for value in _values(histories["failure"], "attempt") if isinstance(value, int)
    ]
    recovery_attempts = [
        value for value in _values(histories["recovery"], "attempt") if isinstance(value, int)
    ]
    _require(
        bool(failure_attempts and recovery_attempts)
        and max(recovery_attempts) > max(failure_attempts),
        "recovery attempt counter did not increase",
    )
    _require(not _glue_ids(histories["replay"]), "replay started a second Glue job")
    _require(not _glue_ids(histories["conflict"]), "conflict started Glue")
    return {"result": "PASS", "execution_count": 8}, histories


def _arguments(run: dict[str, Any]) -> dict[str, str]:
    value = run.get("Arguments", {})
    return value if isinstance(value, dict) else {}


def _validate_scenario_inputs(
    context: EvidenceContext, histories: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    registrations = {
        name: _object(context.root / f"{name}-registration.json")
        for name in ("success", "failure", "temporal", "financial", "tamper")
    }
    registrations["tamper_execution"] = _object(context.root / "tamper-execution-registration.json")
    mapping = {
        "success": "success",
        "replay": "success",
        "conflict": "success",
        "failure": "failure",
        "recovery": "failure",
        "temporal": "temporal",
        "financial": "financial",
        "tamper": "tamper_execution",
    }
    for scenario, registration_name in mapping.items():
        registration = registrations[registration_name]
        started = _started_input(histories[scenario])
        _require(
            started.get("manifest_uri") == registration.get("manifest_uri"),
            f"{scenario}: manifest URI differs from registration",
        )
        _require(
            started.get("manifest_version_id") == registration.get("manifest_version_id"),
            f"{scenario}: manifest version differs from registration",
        )
        expected_digest = (
            "f" * 64 if scenario == "conflict" else registration.get("identity_digest")
        )
        _require(
            started.get("manifest_digest") == expected_digest,
            f"{scenario}: manifest digest differs from registered intent",
        )
    _require(
        (context.root / "tamper-mutation.json").is_file(),
        "tamper mutation receipt is missing",
    )
    return {
        "result": "PASS",
        "registration_count": 6,
        "history_binding_count": 8,
        "tamper_mutation_receipt": "tamper-mutation.json",
    }


def _validate_glue(
    context: EvidenceContext, histories: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    runs = _object(context.root / "glue-job-runs.json").get("JobRuns")
    if not isinstance(runs, list):
        raise EvidenceError("Glue run inventory is missing")
    relevant = [
        run
        for run in runs
        if isinstance(run, dict)
        and str(_arguments(run).get("--BATCH_ID", "")).endswith(f"-{context.run_id}")
    ]
    _require(len(relevant) == 6, "Glue inventory must contain exactly six run-bound jobs")
    expected_by_batch = {
        f"success-{context.run_id}": ("SUCCEEDED", False),
        f"failure-{context.run_id}": (None, None),
        f"temporal-{context.run_id}": ("FAILED", False),
        f"financial-{context.run_id}": ("FAILED", False),
        f"tamper-{context.run_id}": ("FAILED", False),
    }
    failure_runs = []
    for run in relevant:
        args = _arguments(run)
        batch = args.get("--BATCH_ID", "")
        _require(batch in expected_by_batch, f"Glue run has unexpected batch {batch!r}")
        _require(run.get("WorkerType") == "G.1X", "Glue WorkerType must be G.1X")
        _require(int(run.get("NumberOfWorkers", 0)) == 2, "Glue worker count must be two")
        _require(str(run.get("GlueVersion")) == "5.0", "Glue version must be 5.0")
        if batch == f"failure-{context.run_id}":
            failure_runs.append(run)
        else:
            expected_status, expected_injection = expected_by_batch[batch]
            _require(run.get("JobRunState") == expected_status, f"{batch}: wrong Glue status")
            _require(
                str(args.get("--INJECT_FAILURE", "false")).lower()
                == str(expected_injection).lower(),
                f"{batch}: wrong Glue injection flag",
            )
    _require(len(failure_runs) == 2, "failure/recovery must have exactly two Glue attempts")
    injected = [
        run
        for run in failure_runs
        if str(_arguments(run).get("--INJECT_FAILURE", "")).lower() == "true"
    ]
    recovered = [
        run
        for run in failure_runs
        if str(_arguments(run).get("--INJECT_FAILURE", "")).lower() == "false"
    ]
    _require(len(injected) == len(recovered) == 1, "failure/recovery injection topology is invalid")
    _require(injected[0].get("JobRunState") == "FAILED", "injected Glue run did not fail")
    _require(recovered[0].get("JobRunState") == "SUCCEEDED", "recovery Glue run did not succeed")
    for key in ("--GENERATION_ID", "--MANIFEST_URI", "--MANIFEST_VERSION_ID", "--MANIFEST_DIGEST"):
        _require(
            _arguments(injected[0]).get(key) == _arguments(recovered[0]).get(key),
            f"recovery changed immutable {key}",
        )
    all_history_ids = set().union(*(_glue_ids(value) for value in histories.values()))
    _require(
        {str(run.get("Id")) for run in relevant} <= all_history_ids,
        "Glue job IDs do not correlate to execution histories",
    )
    for run in relevant:
        run_id = str(run.get("Id"))
        matched = [name for name, value in histories.items() if run_id in _glue_ids(value)]
        _require(len(matched) == 1, f"Glue run {run_id} has ambiguous execution ownership")
        started = _started_input(histories[matched[0]])
        args = _arguments(run)
        for argument, input_name in (
            ("--BATCH_ID", "batch_id"),
            ("--MANIFEST_URI", "manifest_uri"),
            ("--MANIFEST_VERSION_ID", "manifest_version_id"),
            ("--MANIFEST_DIGEST", "manifest_digest"),
        ):
            _require(
                args.get(argument) == started.get(input_name),
                f"Glue run {run_id} differs from execution input {input_name}",
            )
        _require(
            args.get("--GENERATION_ID") in set(_values(histories[matched[0]], "generation_id")),
            f"Glue run {run_id} generation differs from execution history",
        )
    dpu_seconds = sum(
        float(run.get("DPUSeconds", run.get("ExecutionTime", 0) * 2)) for run in relevant
    )
    return {"result": "PASS", "job_run_count": 6, "dpu_seconds": round(dpu_seconds, 3)}


def _pointer(path: Path) -> tuple[str, int]:
    item = _object(path).get("Item")
    if not isinstance(item, dict):
        raise EvidenceError(f"{path.name}: active pointer item is missing")
    try:
        generation = str(item["active_generation"]["S"])
        version = int(item["pointer_version"]["N"])
    except (KeyError, TypeError, ValueError) as error:
        raise EvidenceError(f"{path.name}: active pointer shape is invalid") from error
    return generation, version


def _validate_control(
    context: EvidenceContext, histories: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    success = context.root / "pointer-after-success.json"
    replay = context.root / "pointer-after-replay.json"
    conflict = context.root / "pointer-after-conflict.json"
    before_failure = context.root / "pointer-before-failure.json"
    after_failure = context.root / "pointer-after-failure.json"
    after_recovery = context.root / "pointer-after-recovery.json"
    no_change_pairs = [
        (success, replay, "replay"),
        (replay, conflict, "conflict"),
        (conflict, before_failure, "pre-failure sequencing"),
        (before_failure, after_failure, "failure"),
        (
            context.root / "pointer-before-temporal.json",
            context.root / "pointer-after-temporal.json",
            "temporal",
        ),
        (
            context.root / "pointer-after-temporal.json",
            context.root / "pointer-before-financial.json",
            "temporal-to-financial sequencing",
        ),
        (
            context.root / "pointer-before-financial.json",
            context.root / "pointer-after-financial.json",
            "financial",
        ),
        (
            context.root / "pointer-after-financial.json",
            context.root / "pointer-after-tamper.json",
            "tamper",
        ),
    ]
    for before, after, scenario in no_change_pairs:
        _require(
            before.read_bytes() == after.read_bytes(),
            f"{scenario} changed the active pointer",
        )
    success_generation, success_version = _pointer(success)
    recovery_generation, recovery_version = _pointer(after_recovery)
    _require(success_version > 0, "success pointer version is invalid")
    _require(
        recovery_version == success_version + 1,
        "recovery did not advance the pointer exactly once",
    )
    recovered_generations = set(_values(histories["recovery"], "generation_id"))
    _require(
        recovery_generation in recovered_generations,
        "active pointer does not name the recovered generation",
    )
    _require(
        (context.root / "pointer-before-temporal.json").read_bytes() == after_recovery.read_bytes(),
        "unexpected pointer movement occurred after recovery",
    )
    stale = _pass(context.root / "stale-publisher" / "summary.json")
    _require("STALE_PUBLISHER:" in str(stale.get("error", "")), "stale publisher signal absent")
    _require(
        stale.get("winner_before") == stale.get("winner_after"), "stale publisher changed winner"
    )
    resolution = _object(context.root / "serving-resolution.json")
    _require(resolution.get("status") == "RESOLVED", "serving generation was not resolved")
    _require(bool(resolution.get("generation_id")), "serving generation is absent")
    _require(int(resolution.get("pointer_version", 0)) > 0, "serving pointer version is invalid")
    _require(
        resolution.get("generation_id") == recovery_generation
        and int(resolution.get("pointer_version", 0)) == recovery_version,
        "serving resolution does not match the recovered active pointer",
    )
    return (
        {
            "result": "PASS",
            "success_generation": success_generation,
            "recovery_generation": recovery_generation,
            "success_pointer_version": success_version,
            "recovery_pointer_version": recovery_version,
            "no_change_scenarios": [
                "replay",
                "conflict",
                "failure",
                "temporal",
                "financial",
                "tamper",
                "stale_publisher",
            ],
        },
        {
            "result": "PASS",
            "generation_id": resolution["generation_id"],
            "pointer_version": resolution["pointer_version"],
        },
    )


def _validate_athena(
    context: EvidenceContext, active: dict[str, Any]
) -> tuple[dict[str, Any], int]:
    generation = str(active["generation_id"])
    total_bytes = 0
    billable_bytes = 0
    for name, minimum_mentions in (("athena-orders.json", 1), ("athena-six-table-serving.json", 6)):
        query = _object(context.root / name).get("QueryExecution")
        if not isinstance(query, dict):
            raise EvidenceError(f"{name}: QueryExecution missing")
        _require(
            query.get("Status", {}).get("State") == "SUCCEEDED", f"{name}: query did not succeed"
        )
        _require(bool(query.get("QueryExecutionId")), f"{name}: query ID missing")
        _require(
            str(query.get("Query", "")).count(generation) >= minimum_mentions,
            f"{name}: query is not pinned to the active generation",
        )
        _require(
            str(query.get("WorkGroup", "")).endswith(f"{context.run_id}-verification"),
            f"{name}: wrong workgroup",
        )
        scanned = int(query.get("Statistics", {}).get("DataScannedInBytes", 0))
        total_bytes += scanned
        billable_bytes += max(scanned, 10 * 1024 * 1024)
    validation = _pass(context.root / "athena-validation.json")
    expected = _object(context.root / "failure-expected-results.json")
    _require(
        validation.get("actual") == validation.get("expected") == expected,
        "Athena business result differs from runtime expected results",
    )
    order_rows = (
        _object(context.root / "athena-orders-results.json").get("ResultSet", {}).get("Rows")
    )
    if not isinstance(order_rows, list) or len(order_rows) != 2:
        raise EvidenceError("Athena business result must contain one header and one data row")
    order_headers = [cell.get("VarCharValue") for cell in order_rows[0].get("Data", [])]
    order_values = [cell.get("VarCharValue") for cell in order_rows[1].get("Data", [])]
    _require(order_headers == ["orders", "gross_cents"], "Athena business headers are invalid")
    _require(
        len(order_values) == 2
        and int(order_values[0]) == expected.get("orders")
        and int(order_values[1]) == expected.get("gross_cents"),
        "Athena business row differs from expected results",
    )
    rows = (
        _object(context.root / "athena-six-table-serving-results.json")
        .get("ResultSet", {})
        .get("Rows")
    )
    _require(
        isinstance(rows, list) and len(rows) == 2,
        "six-table Athena result must be one header and one data row",
    )
    headers = [cell.get("VarCharValue") for cell in rows[0].get("Data", [])]
    _require(
        headers
        == ["orders", "order_lines", "payments", "returns", "inventory_movements", "products"],
        "six-table Athena headers are invalid",
    )
    return {
        "result": "PASS",
        "query_count": 2,
        "data_scanned_bytes": total_bytes,
        "billable_bytes_estimate": billable_bytes,
    }, total_bytes


def _validate_cloudwatch(context: EvidenceContext) -> dict[str, Any]:
    receipt = _pass(context.root / "cloudwatch-export-receipt.json")
    _require(
        receipt.get("pagination_complete") is True,
        "CloudWatch export pagination was not proved complete",
    )
    sources = receipt.get("sources")
    if not isinstance(sources, dict) or set(sources) != {"glue", "states", "lambda"}:
        raise EvidenceError("CloudWatch receipt must cover Glue, States, and Lambda")
    for source in ("glue", "states", "lambda"):
        events = _object(context.root / f"{source}-cloudwatch-events.json").get("events")
        if not isinstance(events, list) or not events:
            raise EvidenceError(f"{source}: CloudWatch export is empty")
        record = sources[source]
        if not isinstance(record, dict):
            raise EvidenceError(f"{source}: CloudWatch receipt is invalid")
        _require(
            int(record.get("event_count", -1)) == len(events), f"{source}: event count mismatch"
        )
        _require(
            f"atlasretail-{context.run_id}" in str(record.get("log_group", "")),
            f"{source}: log group is not run-bound",
        )
    return {"result": "PASS", "source_count": 3}


def _domain(path: Path, *, mode: str | None = None) -> dict[str, Any]:
    value = _pass(path, mode=mode)
    return {"result": "PASS", "evidence": path.name, "sha256": _sha256(path), "detail": value}


def _validate_session(context: EvidenceContext, mode: str) -> dict[str, Any]:
    receipt_path = context.root / f"{mode}-session-receipt.json"
    policy_path = context.root / f"{mode}-session-policy.json"
    receipt = _pass(receipt_path)
    _require(
        receipt.get("aws_account_id") == EXPECTED_ACCOUNT
        and receipt.get("aws_region") == EXPECTED_REGION,
        f"{mode} session is not target-bound",
    )
    _require(
        receipt.get("session_policy_sha256") == _sha256(policy_path),
        f"{mode} session policy digest is wrong",
    )
    policy = _object(policy_path)
    statements = policy.get("Statement")
    if not isinstance(statements, list) or len(statements) != 3:
        raise EvidenceError(f"{mode} session policy statement envelope is invalid")
    regional = statements[0]
    denied = statements[2]
    _require(
        isinstance(regional, dict)
        and regional.get("Effect") == "Allow"
        and regional.get("Condition") == {"StringEquals": {"aws:RequestedRegion": EXPECTED_REGION}},
        f"{mode} session policy is not exact-region bound",
    )
    denied_actions = set(denied.get("Action", [])) if isinstance(denied, dict) else set()
    if mode == "execution":
        _require(
            {"s3:DeleteBucket", "states:Delete*", "kms:ScheduleKeyDeletion"} <= denied_actions,
            "execution session does not deny destructive actions",
        )
        _require(
            "states:StartExecution" not in denied_actions,
            "execution session incorrectly denies the bounded workload",
        )
    elif mode == "teardown":
        _require(
            {
                "states:StartExecution",
                "glue:StartJobRun",
                "athena:StartQueryExecution",
                "dynamodb:CreateTable",
                "lambda:Update*",
            }
            <= denied_actions,
            "teardown session does not deny workload and create/update actions",
        )
    else:
        raise EvidenceError(f"unsupported session mode {mode}")
    return {
        "result": "PASS",
        "receipt": receipt,
        "policy_sha256": _sha256(policy_path),
    }


def validate_execution(context: EvidenceContext) -> dict[str, Any]:
    """Validate every pre-teardown domain and return a non-final checkpoint."""
    provenance = _validate_provenance(context)
    executions, histories = _validate_executions(context)
    glue = _validate_glue(context, histories)
    scenario_inputs = _validate_scenario_inputs(context, histories)
    control, active = _validate_control(context, histories)
    athena, athena_bytes = _validate_athena(context, active)
    cloudwatch = _validate_cloudwatch(context)
    source = _pass(context.root / "source-provenance-validation.json")
    session = _validate_session(context, "execution")
    lease = _pass(context.root / "lease-acquisition.json")
    _require(
        lease.get("owner") == f"{EXPECTED_REPOSITORY}/{context.run_id}", "lease owner is wrong"
    )
    budget = _pass(context.root / "budget-verification.json")
    _require(
        float(budget.get("planned_gross_cost_ceiling_usd", 0)) == context.budget_ceiling_usd,
        "budget ceiling differs from admission",
    )
    glue_estimate = float(glue["dpu_seconds"]) / 3600 * 0.44
    athena_estimate = float(athena["billable_bytes_estimate"]) / 1_000_000_000_000 * 5
    partial_estimate = glue_estimate + athena_estimate
    _require(
        partial_estimate <= context.budget_ceiling_usd,
        "metered Glue and Athena estimate exceeds admitted budget ceiling",
    )
    domains: dict[str, Any] = {
        "admission": _domain(context.root / "admission-receipt.json"),
        "source_provenance": {"result": "PASS", "detail": source},
        "iam_session": {"result": "PASS", "detail": session},
        "account_lease": {"result": "PASS", "detail": lease},
        "terraform_preflight": _domain(context.root / "preflight.json"),
        "saved_apply_plan": _domain(
            context.root / "terraform-apply-plan-validation.json", mode="apply"
        ),
        "deployed_inventory": _domain(context.root / "deployment-verification.json"),
        "scenario_inputs": scenario_inputs,
        "step_functions_histories": executions,
        "glue_job_runs": glue,
        "control_state_transitions": control,
        "active_pointer_comparisons": active,
        "athena_queries_and_results": athena,
        "cloudwatch_logs": cloudwatch,
        "runtime_and_metered_usage": {
            "result": "PASS",
            "glue_dpu_seconds": glue["dpu_seconds"],
            "athena_bytes_scanned": athena_bytes,
            "immediate_partial_cost_estimate_usd": round(partial_estimate, 6),
            "estimate_scope": "Glue compute and minimum-billed Athena queries only",
            "actual_billed_cost_claim": "UNCLAIMED",
        },
        "budget": {"result": "PASS", "detail": budget},
    }
    _require(set(domains) == EXECUTION_DOMAINS, "execution evidence domain set is incomplete")
    manifest_sha = canonical_manifest_sha256(build_execution_manifest(context.root))
    return {
        "schema_version": "1.0",
        "proof": "part4-execution-checkpoint",
        "result": "PASS",
        "claim_level": "UNCLAIMED",
        "execution_state": "AWS_EXECUTION_VALIDATED_PENDING_TEARDOWN",
        "aws_execution": True,
        "teardown_complete": False,
        "provenance": provenance,
        "domains": domains,
        "metered_usage": domains["runtime_and_metered_usage"],
        "evidence_manifest_sha256": manifest_sha,
        "actual_billed_cost_claim": "UNCLAIMED",
        "errors": [],
    }


def finalize_evidence(context: EvidenceContext) -> dict[str, Any]:
    """Emit AWS_VERIFIED only after every contract domain is proved complete."""
    checkpoint_path = context.root / "execution-checkpoint.json"
    checkpoint = _object(checkpoint_path)
    _require(
        checkpoint.get("proof") == "part4-execution-checkpoint",
        "execution checkpoint has wrong proof",
    )
    _require(checkpoint.get("result") == "PASS", "execution checkpoint did not pass")
    _require(checkpoint.get("claim_level") == "UNCLAIMED", "checkpoint made an invalid final claim")
    _require(
        checkpoint.get("execution_state") == "AWS_EXECUTION_VALIDATED_PENDING_TEARDOWN",
        "checkpoint execution state is invalid",
    )
    immutable_manifest = _object(context.root / "execution-evidence-manifest.json")
    _require(
        canonical_manifest_sha256(immutable_manifest) == checkpoint.get("evidence_manifest_sha256"),
        "execution evidence manifest digest differs from checkpoint",
    )
    for relative, expected_sha in immutable_manifest.items():
        _require(
            isinstance(relative, str) and isinstance(expected_sha, str),
            "execution manifest entry is invalid",
        )
        candidate = Path(relative)
        _require(
            not candidate.is_absolute() and ".." not in candidate.parts,
            "execution manifest path escapes evidence root",
        )
        path = context.root / candidate
        _require(
            path.is_file() and _sha256(path) == expected_sha,
            f"execution evidence changed after checkpoint: {relative}",
        )
    _require(checkpoint.get("teardown_complete") is False, "checkpoint teardown flag is invalid")
    domains = dict(checkpoint.get("domains", {}))
    teardown_session = _validate_session(context, "teardown")
    domains["iam_session"] = {
        "result": "PASS",
        "execution": domains["iam_session"],
        "teardown": teardown_session,
    }
    domains["saved_destroy_plan"] = _domain(
        context.root / "terraform-destroy-plan-validation.json", mode="destroy"
    )
    teardown = _pass(context.root / "teardown.json")
    checks = teardown.get("checks")
    if (
        not isinstance(checks, list)
        or not checks
        or not all(isinstance(item, dict) and item.get("deleted") is True for item in checks)
    ):
        raise EvidenceError("teardown inventory contains residue or is empty")
    domains["post_teardown_inventories"] = {"result": "PASS", "detail": teardown}
    lease = _pass(context.root / "lease-release-verification.json")
    _require(
        lease.get("owner") == f"{EXPECTED_REPOSITORY}/{context.run_id}",
        "released lease owner is wrong",
    )
    _require(
        lease.get("lease_absent") is True and lease.get("consistent_read") is True,
        "account lease absence was not consistently verified",
    )
    domains["lease_release"] = {"result": "PASS", "detail": lease}
    post_budget = _pass(context.root / "post-teardown-budget-verification.json")
    _require(
        float(post_budget.get("planned_gross_cost_ceiling_usd", 0)) == context.budget_ceiling_usd,
        "post-teardown budget ceiling differs from admission",
    )
    domains["budget"] = {
        "result": "PASS",
        "pre_teardown": domains["budget"],
        "post_teardown": post_budget,
    }
    domains["final_summary"] = {"result": "PASS", "finalized_after_lease_release": True}
    _require(set(domains) == REQUIRED_EVIDENCE_DOMAINS, "final evidence domain set is incomplete")
    _require(
        all(
            isinstance(value, dict) and value.get("result") == "PASS" for value in domains.values()
        ),
        "one or more final evidence domains did not pass",
    )
    manifest = {
        str(path.relative_to(context.root)): _sha256(path)
        for path in sorted(context.root.rglob("*"))
        if path.is_file() and path.name not in {"final-summary.json", "evidence-manifest.json"}
    }
    manifest_path = context.root / "evidence-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    provenance = dict(checkpoint["provenance"])
    runtime = _object(context.root / "final-runtime-provenance.json")
    _require(runtime.get("result") == "PASS", "final runtime provenance did not pass")
    _require(runtime.get("terraform_version") == "1.11.4", "Terraform runtime version is wrong")
    try:
        started_at = datetime.fromisoformat(str(runtime.get("execution_started_at")))
        finished_at = datetime.fromisoformat(str(runtime.get("execution_finished_at")))
    except ValueError as error:
        raise EvidenceError("runtime timestamps are not ISO-8601") from error
    _require(
        started_at.utcoffset() is not None
        and finished_at.utcoffset() is not None
        and finished_at >= started_at,
        "runtime timestamps are not timezone-aware and monotonic",
    )
    domains["runtime_and_metered_usage"] = {
        **domains["runtime_and_metered_usage"],
        "execution_to_finality_seconds": round((finished_at - started_at).total_seconds(), 3),
    }
    provenance.update(
        {
            "terraform_version": runtime.get("terraform_version"),
            "provider_lock_sha256": _sha256(
                context.repo_root / "infra" / "atlas" / ".terraform.lock.hcl"
            ),
            "apply_plan_sha256": _sha256(context.root / "terraform-apply-plan.json"),
            "destroy_plan_sha256": _sha256(context.root / "terraform-destroy-plan.json"),
            "execution_started_at": runtime.get("execution_started_at"),
            "execution_finished_at": runtime.get("execution_finished_at"),
        }
    )
    _require(
        set(provenance) >= REQUIRED_PROVENANCE_FIELDS,
        "final provenance field set is incomplete",
    )
    _require(
        all(provenance.get(key) not in (None, "") for key in REQUIRED_PROVENANCE_FIELDS),
        "final provenance contains empty required fields",
    )
    return {
        "schema_version": "1.0",
        "proof": "part4-final-evidence",
        "result": "PASS",
        "claim_level": "AWS_VERIFIED",
        "aws_execution": True,
        "production_claim": False,
        "provenance": provenance,
        "domains": domains,
        "checkpoint_sha256": _sha256(checkpoint_path),
        "evidence_manifest_sha256": _sha256(manifest_path),
        "actual_billed_cost_claim": "UNCLAIMED",
        "errors": [],
    }
