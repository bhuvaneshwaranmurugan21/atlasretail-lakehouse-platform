"""Fail-closed pre-AWS admission for the frozen Part 4 bounded run."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from .canonical import digest
from .part4_contract import (
    CONTRACT_RELATIVE_PATH,
    TARGET_RELATIVE_PATH,
    ContractError,
    load_json_object,
    validate_part4_contract_file,
)
from .part4_stage6_prerequisites import (
    PREREQUISITE_SCHEMA_RELATIVE_PATH,
    PrerequisiteError,
    load_prerequisite_receipt,
)
from .provenance import (
    CATALOG_RELATIVE_PATH,
    PROVENANCE_SCHEMA_RELATIVE_PATH,
    ProvenanceError,
    validate_catalog_file,
    validate_manifest_schemas,
    validate_provenance_schema_file,
    verify_materialized_sources,
)

ADMISSION_SCHEMA_RELATIVE_PATH = Path("contracts/part4/admission-receipt.schema.json")
WORKFLOW_NAME = "AWS bounded lab"
POSITIVE_INTEGER_PATTERN = re.compile(r"^[1-9][0-9]*$")
COMMIT_PATTERN = re.compile(r"^[a-f0-9]{40}$")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")

RECEIPT_KEYS = {
    "authorization",
    "bindings",
    "bounds",
    "execution_class",
    "project",
    "prerequisites",
    "receipt_sha256",
    "result",
    "schema_version",
    "sources",
    "workflow",
}


class AdmissionError(ValueError):
    """Raised when a proposed Part 4 run is not exactly admissible."""


@dataclass(frozen=True)
class AdmissionContext:
    """Untrusted dispatch context that must be bound before AWS access."""

    repository: str
    workflow_name: str
    event: str
    ref: str
    actor: str
    repository_owner: str
    source_commit: str
    checked_out_commit: str
    run_id: str
    run_attempt: str
    order_count: str
    budget_ceiling_usd: str
    confirm_execute: str
    confirm_destroy: str
    prerequisite_receipt: Path


def _fail(path: str, observed: object, required: object) -> NoReturn:
    raise AdmissionError(f"{path}: observed {observed!r}; required {required!r}")


def _require_equal(path: str, observed: object, required: object) -> None:
    if observed != required:
        _fail(path, observed, required)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as error:
        raise AdmissionError(f"{path}: unable to read file: {error}") from error


def _positive_integer(value: str, path: str, *, minimum: int, maximum: int) -> int:
    if POSITIVE_INTEGER_PATTERN.fullmatch(value) is None:
        _fail(path, value, f"canonical integer string from {minimum} through {maximum}")
    parsed = int(value)
    if not minimum <= parsed <= maximum:
        _fail(path, parsed, f"integer from {minimum} through {maximum}")
    return parsed


def _validate_schema_shape(schema: dict[str, Any]) -> None:
    expected_keys = {
        "$defs",
        "$id",
        "$schema",
        "additionalProperties",
        "properties",
        "required",
        "title",
        "type",
    }
    _require_equal("admission_schema.keys", set(schema), expected_keys)
    _require_equal(
        "admission_schema.$schema",
        schema["$schema"],
        "https://json-schema.org/draft/2020-12/schema",
    )
    _require_equal("admission_schema.type", schema["type"], "object")
    _require_equal("admission_schema.additionalProperties", schema["additionalProperties"], False)
    _require_equal("admission_schema.required", set(schema["required"]), RECEIPT_KEYS)
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        _fail("admission_schema.properties", type(properties).__name__, "JSON object")
    _require_equal("admission_schema.properties", set(properties), RECEIPT_KEYS)


def validate_admission_schema_file(path: Path) -> str:
    """Validate the checked-in strict receipt schema and return its byte digest."""

    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AdmissionError(f"{path}: unable to load schema: {error}") from error
    if not isinstance(value, dict):
        _fail("admission_schema", type(value).__name__, "JSON object")
    _validate_schema_shape(value)
    return _file_sha256(path)


def _source_tree(source_directory: Path) -> tuple[int, int, str]:
    """Digest exact relative paths, sizes, and bytes for the admitted source tree."""

    if not source_directory.is_dir():
        _fail("source_directory", source_directory.as_posix(), "existing directory")
    entries: list[dict[str, object]] = []
    total_size = 0
    for path in sorted(source_directory.rglob("*")):
        relative = path.relative_to(source_directory).as_posix()
        if path.is_symlink():
            _fail(f"source_tree.{relative}", "symlink", "regular file or directory")
        if path.is_dir():
            continue
        if not path.is_file():
            _fail(f"source_tree.{relative}", "non-regular entry", "regular file")
        size = path.stat().st_size
        total_size += size
        entries.append({"path": relative, "sha256": _file_sha256(path), "size": size})
    if not entries:
        _fail("source_tree.file_count", 0, "at least one file")
    return len(entries), total_size, digest(entries)


def _validate_context(
    context: AdmissionContext, *, contract: dict[str, Any], target: dict[str, Any]
) -> tuple[int, int]:
    authorization = contract["authorization"]
    workload_bounds = contract["workload"]["order_count"]
    cost_bounds = contract["cost"]["run_ceiling_usd"]
    _require_equal("context.repository", context.repository, target["repository"])
    _require_equal("context.workflow_name", context.workflow_name, WORKFLOW_NAME)
    _require_equal("context.event", context.event, authorization["allowed_event"])
    _require_equal("context.ref", context.ref, authorization["allowed_ref"])
    _require_equal(
        "context.repository_owner",
        context.repository_owner,
        target["repository"].split("/")[0],
    )
    _require_equal("context.actor", context.actor, context.repository_owner)
    if COMMIT_PATTERN.fullmatch(context.source_commit) is None:
        _fail("context.source_commit", context.source_commit, "40-character lowercase commit SHA")
    _require_equal("context.checked_out_commit", context.checked_out_commit, context.source_commit)
    if POSITIVE_INTEGER_PATTERN.fullmatch(context.run_id) is None:
        _fail("context.run_id", context.run_id, "positive integer string")
    if POSITIVE_INTEGER_PATTERN.fullmatch(context.run_attempt) is None:
        _fail("context.run_attempt", context.run_attempt, "positive integer string")
    _require_equal(
        "context.confirm_execute",
        context.confirm_execute,
        authorization["execute_confirmation"],
    )
    _require_equal(
        "context.confirm_destroy",
        context.confirm_destroy,
        authorization["destroy_confirmation"],
    )
    if context.confirm_execute == context.confirm_destroy:
        _fail("context.confirmations", context.confirm_execute, "distinct exact confirmations")
    order_count = _positive_integer(
        context.order_count,
        "context.order_count",
        minimum=int(workload_bounds["minimum"]),
        maximum=int(workload_bounds["maximum"]),
    )
    budget = _positive_integer(
        context.budget_ceiling_usd,
        "context.budget_ceiling_usd",
        minimum=int(cost_bounds["minimum"]),
        maximum=int(cost_bounds["maximum"]),
    )
    _require_equal("target.run_ceiling_usd", target["run_ceiling_usd"], cost_bounds["maximum"])
    return order_count, budget


def _build_admission_receipt(
    *, repo_root: Path, source_directory: Path, context: AdmissionContext
) -> dict[str, Any]:
    contract_path = repo_root / CONTRACT_RELATIVE_PATH
    contract_result = validate_part4_contract_file(contract_path, repo_root=repo_root)
    contract = load_json_object(contract_path)
    target = load_json_object(repo_root / TARGET_RELATIVE_PATH)
    order_count, budget = _validate_context(context, contract=contract, target=target)
    schema_sha256 = validate_admission_schema_file(repo_root / ADMISSION_SCHEMA_RELATIVE_PATH)
    catalog_result = validate_catalog_file(repo_root / CATALOG_RELATIVE_PATH, repo_root=repo_root)
    source_schema_sha256, managed_schema_sha256 = validate_manifest_schemas(repo_root=repo_root)
    provenance_schema_sha256 = validate_provenance_schema_file(
        repo_root / PROVENANCE_SCHEMA_RELATIVE_PATH
    )
    summary = verify_materialized_sources(source_directory, repo_root=repo_root)
    prerequisite_receipt = load_prerequisite_receipt(
        context.prerequisite_receipt,
        schema_path=repo_root / PREREQUISITE_SCHEMA_RELATIVE_PATH,
    )
    prerequisite_identity = prerequisite_receipt["source_identity"]
    _require_equal(
        "prerequisites.source_commit",
        prerequisite_identity.get("source_commit"),
        context.source_commit,
    )
    _require_equal(
        "prerequisites.repository",
        prerequisite_identity.get("repository"),
        context.repository,
    )
    _require_equal("prerequisites.ref", prerequisite_identity.get("ref"), context.ref)
    _require_equal("sources.order_count", summary.get("order_count"), order_count)
    _require_equal("sources.source_commit", summary.get("source_commit"), context.source_commit)
    file_count, source_bytes, tree_sha256 = _source_tree(source_directory)
    summary_file = source_directory / "source-provenance-summary.json"
    payload: dict[str, Any] = {
        "authorization": {
            "destroy_confirmation": context.confirm_destroy,
            "distinct_confirmations": True,
            "execute_confirmation": context.confirm_execute,
            "operator_is_repository_owner": True,
        },
        "bindings": {
            "admission_schema_sha256": schema_sha256,
            "aws_account_id": target["aws_account_id"],
            "aws_region": target["aws_region"],
            "catalog_sha256": catalog_result.catalog_sha256,
            "contract_id": contract["contract_id"],
            "contract_sha256": contract_result.contract_sha256,
            "contract_version": contract["version"],
            "managed_manifest_schema_sha256": managed_schema_sha256,
            "oidc_role_arn": target["oidc_role_arn"],
            "provenance_schema_sha256": provenance_schema_sha256,
            "source_manifest_schema_sha256": source_schema_sha256,
            "target_sha256": contract_result.target_sha256,
        },
        "bounds": {
            "budget_ceiling_usd": budget,
            "order_count": order_count,
            "runtime_expansion_prohibited": True,
        },
        "execution_class": contract["execution_class"],
        "project": contract["project"],
        "prerequisites": {
            "receipt_sha256": prerequisite_receipt["receipt_sha256"],
            **prerequisite_receipt["prerequisite_runs"],
        },
        "result": "PASS",
        "schema_version": "1.0",
        "sources": {
            "file_count": file_count,
            "scenario_count": summary["scenario_count"],
            "source_bytes": source_bytes,
            "source_family_count": summary["source_family_count"],
            "source_provenance_summary_file_sha256": _file_sha256(summary_file),
            "source_provenance_summary_sha256": summary["summary_sha256"],
            "source_tree_sha256": tree_sha256,
        },
        "workflow": {
            "actor": context.actor,
            "event": context.event,
            "ref": context.ref,
            "repository": context.repository,
            "repository_owner": context.repository_owner,
            "run_attempt": context.run_attempt,
            "run_id": context.run_id,
            "source_commit": context.source_commit,
            "workflow_name": context.workflow_name,
        },
    }
    return {**payload, "receipt_sha256": digest(payload)}


def build_admission_receipt(
    *, repo_root: Path, source_directory: Path, context: AdmissionContext
) -> dict[str, Any]:
    """Build one deterministic admission receipt after every boundary passes."""

    try:
        return _build_admission_receipt(
            repo_root=repo_root, source_directory=source_directory, context=context
        )
    except AdmissionError:
        raise
    except (ContractError, PrerequisiteError, ProvenanceError, OSError) as error:
        raise AdmissionError(str(error)) from error


def verify_admission_receipt(
    receipt: dict[str, Any], *, repo_root: Path, source_directory: Path, context: AdmissionContext
) -> dict[str, Any]:
    """Rebuild and compare the complete receipt from the downloaded source tree."""

    _require_equal("receipt.keys", set(receipt), RECEIPT_KEYS)
    supplied_digest = receipt.get("receipt_sha256")
    if not isinstance(supplied_digest, str) or SHA256_PATTERN.fullmatch(supplied_digest) is None:
        _fail("receipt.receipt_sha256", supplied_digest, "lowercase SHA-256")
    payload = dict(receipt)
    payload.pop("receipt_sha256")
    _require_equal("receipt.receipt_sha256", supplied_digest, digest(payload))
    expected = build_admission_receipt(
        repo_root=repo_root, source_directory=source_directory, context=context
    )
    _require_equal("receipt", receipt, expected)
    return expected


def load_receipt(path: Path) -> dict[str, Any]:
    """Load an admission receipt without accepting non-object JSON."""

    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AdmissionError(f"{path}: unable to load receipt: {error}") from error
    if not isinstance(value, dict):
        _fail("receipt", type(value).__name__, "JSON object")
    return value


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    """Write a receipt atomically enough for the single-process CI producer."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
