"""Validation for the frozen AtlasRetail Part 4 bounded-execution contract."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

CONTRACT_RELATIVE_PATH = Path("contracts/part4/run-contract.json")
TARGET_RELATIVE_PATH = Path(".github/atlas-target.json")
FORBIDDEN_REGION = "ap-" + "south-1"

EXPECTED_TOP_LEVEL_KEYS = {
    "authorization",
    "change_control",
    "claim_policy",
    "contract_id",
    "cost",
    "evidence",
    "execution_class",
    "project",
    "scenarios",
    "schema_version",
    "target_binding",
    "teardown",
    "version",
    "workload",
}
EXPECTED_TARGET_VALUES: dict[str, object] = {
    "aws_account_id": "857229544428",
    "aws_region": "ap-southeast-2",
    "branch_ref": "refs/heads/main",
    "oidc_role_arn": "arn:aws:iam::857229544428:role/AtlasRetailGitHubOidcRole",
    "repository": "bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform",
    "run_ceiling_usd": 5,
}
EXPECTED_SCENARIOS: dict[str, dict[str, object]] = {
    "success": {
        "expected_result": "SUCCEEDED",
        "failure_signal": None,
        "glue_job_run": True,
        "pointer_effect": "ADVANCE_EXACTLY_ONCE",
        "proof_kind": "STEP_FUNCTIONS_EXECUTION",
        "required_assertions": ["GENERATION_VALIDATED", "GENERATION_PUBLISHED"],
        "step_functions_execution": True,
    },
    "replay": {
        "expected_result": "SUCCEEDED",
        "failure_signal": None,
        "glue_job_run": False,
        "pointer_effect": "NO_CHANGE",
        "proof_kind": "STEP_FUNCTIONS_EXECUTION",
        "required_assertions": ["SAME_BATCH_IDENTITY", "NO_SECOND_LOGICAL_GENERATION"],
        "step_functions_execution": True,
    },
    "conflict": {
        "expected_result": "FAILED",
        "failure_signal": "CONFLICT:",
        "glue_job_run": False,
        "pointer_effect": "NO_CHANGE",
        "proof_kind": "STEP_FUNCTIONS_EXECUTION",
        "required_assertions": ["REUSED_BATCH_HAS_DIFFERENT_CONTENT"],
        "step_functions_execution": True,
    },
    "failure": {
        "expected_result": "FAILED",
        "failure_signal": "INJECTED_FAILURE",
        "glue_job_run": True,
        "pointer_effect": "NO_CHANGE",
        "proof_kind": "STEP_FUNCTIONS_EXECUTION",
        "required_assertions": ["FAILED_GENERATION_REMAINS_RECOVERABLE"],
        "step_functions_execution": True,
    },
    "recovery": {
        "expected_result": "SUCCEEDED",
        "failure_signal": None,
        "glue_job_run": True,
        "pointer_effect": "ADVANCE_EXACTLY_ONCE",
        "proof_kind": "STEP_FUNCTIONS_EXECUTION",
        "required_assertions": [
            "SAME_BATCH_IDENTITY_AS_FAILURE",
            "SAME_GENERATION_ID_AS_FAILURE",
            "ATTEMPT_COUNTER_INCREASED",
            "VALIDATED_BEFORE_PUBLICATION",
        ],
        "step_functions_execution": True,
    },
    "temporal": {
        "expected_result": "FAILED",
        "failure_signal": "QUALITY_GATE:AMBIGUOUS_DIMENSION",
        "glue_job_run": True,
        "pointer_effect": "NO_CHANGE",
        "proof_kind": "STEP_FUNCTIONS_EXECUTION",
        "required_assertions": ["OVERLAPPING_DIMENSION_REJECTED"],
        "step_functions_execution": True,
    },
    "financial": {
        "expected_result": "FAILED",
        "failure_signal": "QUALITY_GATE:ORDER_TOTAL",
        "glue_job_run": True,
        "pointer_effect": "NO_CHANGE",
        "proof_kind": "STEP_FUNCTIONS_EXECUTION",
        "required_assertions": ["ORDER_TOTAL_IMBALANCE_REJECTED"],
        "step_functions_execution": True,
    },
    "tamper": {
        "expected_result": "FAILED",
        "failure_signal": "QUALITY_GATE:OBJECT_IDENTITY",
        "glue_job_run": True,
        "pointer_effect": "NO_CHANGE",
        "proof_kind": "STEP_FUNCTIONS_EXECUTION",
        "required_assertions": ["S3_VERSION_BYTES_CONTRADICT_EVIDENCE"],
        "step_functions_execution": True,
    },
    "stale_publisher": {
        "expected_result": "PASS",
        "failure_signal": "STALE_PUBLISHER:",
        "glue_job_run": False,
        "pointer_effect": "NO_CHANGE",
        "proof_kind": "DIRECT_CONTROL_PLANE_PROOF",
        "required_assertions": ["COMPARE_AND_SWAP_REJECTED", "WINNER_REMAINS_ACTIVE"],
        "step_functions_execution": False,
    },
    "athena_verification": {
        "expected_result": "PASS",
        "failure_signal": None,
        "glue_job_run": False,
        "pointer_effect": "READ_ONE_ACTIVE_GENERATION",
        "proof_kind": "ATHENA_QUERY_PROOF",
        "required_assertions": [
            "RUNTIME_EXPECTED_RESULTS_MATCH",
            "SIX_TABLE_SERVING_QUERY_ONE_DATA_ROW",
            "QUERY_IDS_AND_SCANNED_BYTES_RECORDED",
        ],
        "step_functions_execution": False,
    },
}
REQUIRED_EVIDENCE_DOMAINS = {
    "admission",
    "source_provenance",
    "iam_session",
    "account_lease",
    "terraform_preflight",
    "saved_apply_plan",
    "deployed_inventory",
    "scenario_inputs",
    "step_functions_histories",
    "glue_job_runs",
    "control_state_transitions",
    "active_pointer_comparisons",
    "athena_queries_and_results",
    "cloudwatch_logs",
    "runtime_and_metered_usage",
    "budget",
    "saved_destroy_plan",
    "post_teardown_inventories",
    "lease_release",
    "final_summary",
}
REQUIRED_PROVENANCE_FIELDS = {
    "repository",
    "workflow_name",
    "workflow_run_id",
    "workflow_attempt",
    "source_commit",
    "contract_version",
    "contract_sha256",
    "target_sha256",
    "aws_account_id",
    "aws_region",
    "oidc_role_arn",
    "terraform_version",
    "provider_lock_sha256",
    "apply_plan_sha256",
    "destroy_plan_sha256",
    "execution_started_at",
    "execution_finished_at",
}


class ContractError(ValueError):
    """Raised when the Part 4 contract is absent, ambiguous, or weakened."""


@dataclass(frozen=True)
class ContractValidation:
    """Deterministic result returned after the complete contract passes."""

    contract_sha256: str
    target_sha256: str
    scenario_count: int
    step_functions_execution_count: int
    glue_job_run_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_sha256": self.contract_sha256,
            "glue_job_run_count": self.glue_job_run_count,
            "result": "PASS",
            "scenario_count": self.scenario_count,
            "step_functions_execution_count": self.step_functions_execution_count,
            "target_sha256": self.target_sha256,
        }


def _fail(path: str, observed: object, required: object) -> NoReturn:
    raise ContractError(f"{path}: observed {observed!r}; required {required!r}")


def _require_equal(path: str, observed: object, required: object) -> None:
    if observed != required:
        _fail(path, observed, required)


def _object(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(path, type(value).__name__, "JSON object")
    return value


def _list(value: object, path: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(path, type(value).__name__, "JSON array")
    return value


def canonical_json_bytes(value: object) -> bytes:
    """Return one stable JSON representation for contract evidence hashing."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"{path}: unable to load JSON: {error}") from error
    return _object(value, str(path))


def _validate_identity(contract: dict[str, Any]) -> None:
    _require_equal("schema_version", contract["schema_version"], "1.0")
    _require_equal("version", contract["version"], "1.0.0")
    _require_equal("contract_id", contract["contract_id"], "atlasretail-part4-bounded-execution")
    _require_equal("project", contract["project"], "AtlasRetail")
    _require_equal("execution_class", contract["execution_class"], "BOUNDED_NON_PRODUCTION_LAB")


def _validate_target(contract: dict[str, Any], repo_root: Path) -> str:
    binding = _object(contract["target_binding"], "target_binding")
    _require_equal(
        "target_binding.keys",
        set(binding),
        {"path", "sha256", "required_values", "forbidden_regions"},
    )
    _require_equal("target_binding.path", binding["path"], TARGET_RELATIVE_PATH.as_posix())
    _require_equal(
        "target_binding.forbidden_regions",
        binding["forbidden_regions"],
        [FORBIDDEN_REGION],
    )
    required_values = _object(binding["required_values"], "target_binding.required_values")
    _require_equal("target_binding.required_values", required_values, EXPECTED_TARGET_VALUES)

    target_path = repo_root / TARGET_RELATIVE_PATH
    try:
        target_bytes = target_path.read_bytes()
    except OSError as error:
        raise ContractError(f"{target_path}: unable to read target: {error}") from error
    target_digest = hashlib.sha256(target_bytes).hexdigest()
    _require_equal("target_binding.sha256", binding["sha256"], target_digest)
    target = load_json_object(target_path)
    for key, required in EXPECTED_TARGET_VALUES.items():
        _require_equal(f"target.{key}", target.get(key), required)
    if target["aws_region"] in binding["forbidden_regions"]:
        _fail("target.aws_region", target["aws_region"], "region outside forbidden_regions")
    return target_digest


def _validate_authorization(contract: dict[str, Any]) -> None:
    authorization = _object(contract["authorization"], "authorization")
    expected = {
        "allowed_event": "workflow_dispatch",
        "allowed_ref": "refs/heads/main",
        "destroy_confirmation": "DESTROY",
        "execute_confirmation": "EXECUTE_ATLASRETAIL_PART4",
        "persist_teardown_authority_before_mutation": True,
        "require_distinct_confirmations": True,
    }
    _require_equal("authorization", authorization, expected)
    if authorization["execute_confirmation"] == authorization["destroy_confirmation"]:
        _fail("authorization confirmations", authorization, "distinct exact tokens")


def _validate_bounds(contract: dict[str, Any]) -> None:
    workload = _object(contract["workload"], "workload")
    _require_equal(
        "workload",
        workload,
        {
            "order_count": {"default": 500, "maximum": 2000, "minimum": 100},
            "runtime_expansion_prohibited": True,
        },
    )
    cost = _object(contract["cost"], "cost")
    _require_equal(
        "cost",
        cost,
        {
            "actual_billed_cost_claim": "UNCLAIMED",
            "fresh_account_plan_or_owner_attestation_required": True,
            "run_ceiling_usd": {"default": 5, "maximum": 5, "minimum": 1},
        },
    )


def _validate_scenarios(contract: dict[str, Any]) -> tuple[int, int, int]:
    scenarios = _list(contract["scenarios"], "scenarios")
    by_name: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(scenarios):
        scenario = _object(value, f"scenarios[{index}]")
        name = scenario.get("name")
        if not isinstance(name, str) or not name:
            _fail(f"scenarios[{index}].name", name, "non-empty string")
        if name in by_name:
            _fail(f"scenarios[{index}].name", name, "unique scenario name")
        by_name[name] = scenario
    _require_equal("scenario names", set(by_name), set(EXPECTED_SCENARIOS))
    for name, expected in EXPECTED_SCENARIOS.items():
        scenario = dict(by_name[name])
        scenario.pop("name", None)
        _require_equal(f"scenarios.{name}", scenario, expected)

    step_functions_count = sum(
        bool(value["step_functions_execution"]) for value in by_name.values()
    )
    glue_run_count = sum(bool(value["glue_job_run"]) for value in by_name.values())
    _require_equal("aggregate.step_functions_execution_count", step_functions_count, 8)
    _require_equal("aggregate.glue_job_run_count", glue_run_count, 6)
    return len(scenarios), step_functions_count, glue_run_count


def _validate_evidence(contract: dict[str, Any]) -> None:
    evidence = _object(contract["evidence"], "evidence")
    _require_equal(
        "evidence.keys",
        set(evidence),
        {
            "artifact_upload_required",
            "cloudwatch_exports",
            "failure_policy",
            "required_domains",
            "required_provenance_fields",
            "sensitive_values_excluded",
        },
    )
    _require_equal(
        "evidence.artifact_upload_required",
        evidence.get("artifact_upload_required"),
        True,
    )
    _require_equal(
        "evidence.failure_policy",
        evidence.get("failure_policy"),
        "ANY_MISSING_OR_FAILED_EVIDENCE_FAILS_RUN",
    )
    _require_equal(
        "evidence.required_domains",
        set(_list(evidence.get("required_domains"), "evidence.required_domains")),
        REQUIRED_EVIDENCE_DOMAINS,
    )
    _require_equal(
        "evidence.required_provenance_fields",
        set(
            _list(
                evidence.get("required_provenance_fields"),
                "evidence.required_provenance_fields",
            )
        ),
        REQUIRED_PROVENANCE_FIELDS,
    )
    cloudwatch = _object(evidence.get("cloudwatch_exports"), "evidence.cloudwatch_exports")
    _require_equal(
        "evidence.cloudwatch_exports",
        cloudwatch,
        {"non_empty_required": True, "sources": ["glue", "states", "lambda"]},
    )
    _require_equal(
        "evidence.sensitive_values_excluded",
        set(
            _list(
                evidence.get("sensitive_values_excluded"),
                "evidence.sensitive_values_excluded",
            )
        ),
        {"aws_credentials", "oidc_tokens", "session_tokens", "signed_urls"},
    )


def _validate_teardown_and_claims(contract: dict[str, Any]) -> None:
    teardown = _object(contract["teardown"], "teardown")
    required_teardown = {
        "always_run_after_admitted_mutation",
        "apply_only_validated_saved_destroy_plan",
        "clean_aws_inventory_required",
        "empty_terraform_state_required",
        "kms_pending_deletion_requires_alias_absent",
        "lease_release_requires_clean_teardown",
        "saved_destroy_plan_must_be_destroy_only",
        "successful_workload_with_failed_teardown_is_failure",
    }
    _require_equal("teardown.keys", set(teardown), required_teardown)
    for key in required_teardown:
        _require_equal(f"teardown.{key}", teardown[key], True)

    claims = _object(contract["claim_policy"], "claim_policy")
    _require_equal(
        "claim_policy",
        claims,
        {
            "allowed_levels": [
                "LOCAL_VERIFIED",
                "AWS_VERIFIED",
                "DESIGNED/MODELED",
                "UNCLAIMED",
            ],
            "aws_verified_requires_complete_evidence": True,
            "aws_verified_requires_clean_teardown": True,
            "production_claim": False,
            "prohibited_claims": [
                "PRODUCTION_READY",
                "PRODUCTION_SCALE",
                "SLA_PROVEN",
                "SETTLED_BILLING_PROVEN",
            ],
            "stage_1_result_after_validation": "LOCAL_VERIFIED",
        },
    )

    change_control = _object(contract["change_control"], "change_control")
    _require_equal(
        "change_control",
        change_control,
        {
            "invalidate_bound_prerequisites_on_semantic_change": True,
            "require_rationale": True,
            "require_test_updates": True,
            "semantic_changes_require_version_increment": True,
        },
    )


def validate_part4_contract(contract: dict[str, Any], *, repo_root: Path) -> ContractValidation:
    """Fail closed unless the complete frozen contract and target binding agree."""

    _require_equal("top-level keys", set(contract), EXPECTED_TOP_LEVEL_KEYS)
    _validate_identity(contract)
    target_digest = _validate_target(contract, repo_root)
    _validate_authorization(contract)
    _validate_bounds(contract)
    scenario_count, step_functions_count, glue_run_count = _validate_scenarios(contract)
    _validate_evidence(contract)
    _validate_teardown_and_claims(contract)
    return ContractValidation(
        contract_sha256=canonical_sha256(contract),
        target_sha256=target_digest,
        scenario_count=scenario_count,
        step_functions_execution_count=step_functions_count,
        glue_job_run_count=glue_run_count,
    )


def validate_part4_contract_file(
    path: Path, *, repo_root: Path | None = None
) -> ContractValidation:
    root = repo_root if repo_root is not None else path.resolve().parents[2]
    return validate_part4_contract(load_json_object(path), repo_root=root)
