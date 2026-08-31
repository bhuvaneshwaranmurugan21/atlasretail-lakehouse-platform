"""Deterministic Part 4 Stage 7 closure and runtime-equivalence evidence."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from .canonical import digest

EXPECTED_ACCOUNT = "857229544428"
EXPECTED_REGION = "ap-southeast-2"
EXPECTED_PROJECT = "AtlasRetail"
EXPECTED_REPOSITORY = "bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform"
STAGE6_SOURCE_COMMIT = "08559b0f48708080335282c6d59faa3826635d67"
STAGE6_BOUNDED_RUN_ID = 33329861907
STAGE6_RECOVERY_RUN_ID = 33328391707
CLOSURE_SCHEMA = Path("contracts/part4/stage7-closure.schema.json")
RUNTIME_MANIFEST = Path("contracts/part4/stage7-runtime-manifest.json")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ClosureError(ValueError):
    """Raised when Stage 7 evidence is incomplete, stale, or inconsistent."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ClosureError(message)


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ClosureError(f"{path}: unreadable JSON: {error}") from error
    if not isinstance(value, dict):
        raise ClosureError(f"{path}: expected a JSON object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ClosureError(f"{label}: timestamp is absent")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ClosureError(f"{label}: invalid timestamp") from error
    _require(parsed.tzinfo is not None, f"{label}: timestamp has no timezone")
    return parsed


def load_runtime_manifest(path: Path) -> dict[str, Any]:
    """Load and strictly validate the frozen Stage 6 runtime manifest."""

    manifest = _load_object(path)
    expected_keys = {
        "baseline_source_commit",
        "digest_scheme",
        "evidence_type",
        "expected_file_count",
        "expected_files_sha256",
        "project",
        "schema_version",
        "selection",
        "stage7_only_allowlist",
    }
    _require(set(manifest) == expected_keys, "runtime manifest keys differ")
    _require(manifest["schema_version"] == "1.0", "runtime manifest schema differs")
    _require(manifest["project"] == EXPECTED_PROJECT, "runtime manifest project differs")
    _require(
        manifest["evidence_type"] == "part4-stage7-frozen-runtime-surface",
        "runtime manifest evidence type differs",
    )
    _require(
        manifest["baseline_source_commit"] == STAGE6_SOURCE_COMMIT,
        "runtime baseline source differs",
    )
    _require(
        manifest["digest_scheme"] == "canonical-path-sha256-map-v1",
        "runtime digest scheme differs",
    )
    _require(manifest["expected_file_count"] == 107, "runtime file count is not frozen")
    expected_digest = manifest["expected_files_sha256"]
    _require(
        isinstance(expected_digest, str) and SHA256_PATTERN.fullmatch(expected_digest) is not None,
        "runtime aggregate digest is invalid",
    )
    selection = manifest["selection"]
    _require(
        isinstance(selection, dict) and set(selection) == {"exact_files", "roots"},
        "runtime selection keys differ",
    )
    roots = selection["roots"]
    exact_files = selection["exact_files"]
    _require(
        roots == ["aws", "contracts", "infra", "scripts", "src"],
        "runtime roots differ",
    )
    _require(
        isinstance(exact_files, list)
        and len(exact_files) == 10
        and len(set(exact_files)) == 10
        and all(
            isinstance(value, str)
            and value.startswith(".github/workflows/aws-")
            and value.endswith(".yml")
            for value in exact_files
        ),
        "runtime workflow selection differs",
    )
    allowlist = manifest["stage7_only_allowlist"]
    _require(
        isinstance(allowlist, list)
        and len(allowlist) == len(set(allowlist))
        and all(isinstance(value, str) for value in allowlist),
        "Stage 7 allowlist is invalid",
    )
    return manifest


def tracked_runtime_paths(repository: Path, manifest: dict[str, Any]) -> list[str]:
    """Return tracked runtime paths after excluding exact closure-only additions."""

    try:
        completed = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=repository,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ClosureError("tracked runtime inventory is unavailable") from error
    tracked = [value.decode() for value in completed.stdout.split(b"\0") if value]
    selection = manifest["selection"]
    roots = tuple(f"{value}/" for value in selection["roots"])
    exact = set(selection["exact_files"])
    allowlist = set(manifest["stage7_only_allowlist"])
    return sorted(
        path
        for path in tracked
        if (path.startswith(roots) or path in exact) and path not in allowlist
    )


def build_runtime_receipt(
    repository: Path,
    manifest_path: Path | None = None,
    *,
    paths: list[str] | None = None,
) -> dict[str, Any]:
    """Prove current managed runtime bytes equal the frozen Stage 6 surface."""

    resolved_manifest = manifest_path or repository / RUNTIME_MANIFEST
    manifest = load_runtime_manifest(resolved_manifest)
    selected = paths if paths is not None else tracked_runtime_paths(repository, manifest)
    _require(len(selected) == len(set(selected)), "runtime path inventory contains duplicates")
    file_sha256: dict[str, str] = {}
    for relative in sorted(selected):
        path = repository / relative
        _require(not path.is_symlink(), f"runtime path is a symbolic link: {relative}")
        _require(path.is_file(), f"runtime path is absent or irregular: {relative}")
        file_sha256[relative] = _sha256(path)
    aggregate = digest(file_sha256)
    errors: list[str] = []
    if len(selected) != manifest["expected_file_count"]:
        errors.append("runtime file count differs from the frozen Stage 6 surface")
    if aggregate != manifest["expected_files_sha256"]:
        errors.append("runtime bytes differ from the frozen Stage 6 surface")
    return {
        "baseline_source_commit": manifest["baseline_source_commit"],
        "file_count": len(selected),
        "files_sha256": aggregate,
        "result": "PASS" if not errors else "FAIL",
        "errors": errors,
    }


def _verify_committed_directory(directory: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = _load_object(directory / "manifest.json")
    committed_value = manifest.get("committed_summaries")
    if not isinstance(committed_value, dict) or not committed_value:
        raise ClosureError(f"{directory}: committed summaries absent")
    committed: dict[str, Any] = committed_value
    expected_names = set(committed) | {"manifest.json"}
    observed_names: set[str] = set()
    for path in directory.iterdir():
        _require(not path.is_symlink(), f"{directory}: symbolic links are prohibited")
        _require(path.is_file(), f"{directory}: nested or irregular entries are prohibited")
        observed_names.add(path.name)
    _require(observed_names == expected_names, f"{directory}: committed file set differs")
    for name, expected_digest in committed.items():
        _require(
            isinstance(name, str)
            and isinstance(expected_digest, str)
            and SHA256_PATTERN.fullmatch(expected_digest) is not None,
            f"{directory}: committed digest entry is invalid",
        )
        _require(
            _sha256(directory / name) == expected_digest, f"{directory}/{name}: digest differs"
        )
    summary = _load_object(directory / "summary.json")
    return manifest, summary


def publish_preflight_evidence(
    *,
    raw_directory: Path,
    output_directory: Path,
    artifact: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate raw read-only evidence and publish only sanitized Stage 7 summaries."""

    identity = _load_object(raw_directory / "source-identity.json")
    preflight = _load_object(raw_directory / "preflight.json")
    account_plan = _load_object(raw_directory / "account-plan-verification.json")
    expected_identity = {
        "aws_account_id": EXPECTED_ACCOUNT,
        "aws_region": EXPECTED_REGION,
        "github_run_id": str(identity.get("github_run_id")),
        "oidc_role_arn": f"arn:aws:iam::{EXPECTED_ACCOUNT}:role/AtlasRetailGitHubOidcRole",
        "project": EXPECTED_PROJECT,
        "ref": "refs/heads/main",
        "repository": EXPECTED_REPOSITORY,
        "result": "PASS",
        "run_ceiling_usd": 5,
        "schema_version": "1.0",
        "source_commit": identity.get("source_commit"),
        "terraform_state_key": "atlasretail/main.tfstate",
    }
    _require(identity == expected_identity, "Stage 7 preflight source identity differs")
    source_commit = identity["source_commit"]
    _require(
        isinstance(source_commit, str) and COMMIT_PATTERN.fullmatch(source_commit) is not None,
        "Stage 7 preflight source commit is invalid",
    )
    run_id = int(identity["github_run_id"])
    _require(preflight.get("result") == "PASS", "Stage 7 preflight did not pass")
    _require(preflight.get("errors") == [], "Stage 7 preflight contains errors")
    _require(preflight.get("account_lease_absent") is True, "account lease is not absent")
    _require(preflight.get("terraform_state_resources") == [], "Terraform state is not empty")
    _require(preflight.get("unexpected_resources") == [], "unexpected active resources exist")
    _require(
        preflight.get("kms_inspection_errors") == [], "KMS inventory contains inspection errors"
    )
    aliases = preflight.get("pending_deletion_kms_aliases")
    keys = preflight.get("pending_deletion_kms_keys")
    _require(isinstance(aliases, list) and not aliases, "pending-deletion KMS aliases remain")
    if not isinstance(keys, list):
        raise ClosureError("pending-deletion KMS key inventory is absent")
    _require(account_plan.get("result") == "PASS", "account-plan verification did not pass")
    _require(
        account_plan.get("credit_source") == "organization-shared",
        "organization-shared credit was not selected",
    )
    _require(
        float(account_plan.get("organization_shared_credit_usd", 0)) >= 5,
        "verified organization-shared credit is below the bound",
    )
    expected_artifact_keys = {"created_at", "id", "name", "sha256", "size_bytes"}
    _require(set(artifact) == expected_artifact_keys, "preflight artifact metadata keys differ")
    _require(
        all(
            isinstance(artifact[name], int) and artifact[name] > 0 for name in ("id", "size_bytes")
        ),
        "preflight artifact numeric metadata is invalid",
    )
    _require(
        isinstance(artifact["sha256"], str)
        and SHA256_PATTERN.fullmatch(artifact["sha256"]) is not None,
        "preflight artifact digest is invalid",
    )
    _timestamp(artifact["created_at"], "preflight artifact created_at")
    summary = {
        "account_lease_absent": True,
        "aws_account_id": EXPECTED_ACCOUNT,
        "aws_mutation": False,
        "aws_region": EXPECTED_REGION,
        "claim_level": "AWS_VERIFIED",
        "evidence_type": "part4-stage7-final-read-only-preflight",
        "kms_inspection_error_count": 0,
        "pending_deletion_kms_alias_count": 0,
        "pending_deletion_kms_key_count": len(keys),
        "production_claim": False,
        "result": "PASS",
        "run_id": run_id,
        "source_commit": source_commit,
        "terraform_state_resources": [],
        "unexpected_resources": [],
        "workload_execution": False,
    }
    summary_bytes = (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode()
    source_names = ("account-plan-verification.json", "preflight.json", "source-identity.json")
    manifest = {
        "artifact": artifact,
        "aws_account_id": EXPECTED_ACCOUNT,
        "aws_region": EXPECTED_REGION,
        "committed_summaries": {"summary.json": hashlib.sha256(summary_bytes).hexdigest()},
        "evidence_type": "part4-stage7-final-read-only-preflight",
        "production_claim": False,
        "project": EXPECTED_PROJECT,
        "repository": EXPECTED_REPOSITORY,
        "result": "PASS",
        "run_id": run_id,
        "sanitization": {
            "caller_identity": "EXCLUDED",
            "live_resource_identifiers": "EXCLUDED",
            "pending_deletion_kms_identifiers": "REPLACED_WITH_COUNTS",
        },
        "schema_version": "1.0",
        "source_commit": source_commit,
        "source_evidence_sha256": {name: _sha256(raw_directory / name) for name in source_names},
        "workflow": "AWS read-only preflight",
    }
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "summary.json").write_bytes(summary_bytes)
    (output_directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest, summary


def build_closure_receipt(
    *,
    repository: Path,
    bounded_directory: Path,
    recovery_directory: Path,
    preflight_directory: Path,
    control_commit: str,
    runtime_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Build the deterministic, sanitized Stage 7 completion receipt."""

    _require(COMMIT_PATTERN.fullmatch(control_commit) is not None, "control commit is invalid")
    bounded_manifest, bounded = _verify_committed_directory(bounded_directory)
    recovery_manifest, recovery = _verify_committed_directory(recovery_directory)
    preflight_manifest, preflight = _verify_committed_directory(preflight_directory)

    _require(bounded_manifest.get("run_id") == STAGE6_BOUNDED_RUN_ID, "bounded run differs")
    _require(bounded.get("result") == "PASS", "bounded summary did not pass")
    _require(bounded.get("claim_level") == "AWS_VERIFIED", "bounded claim is not AWS verified")
    _require(bounded.get("source_commit") == STAGE6_SOURCE_COMMIT, "bounded source differs")
    _require(bounded.get("production_claim") is False, "bounded production claim changed")
    _require(
        bounded.get("actual_billed_cost_claim") == "UNCLAIMED",
        "bounded settled-cost boundary changed",
    )
    _require(
        bounded.get("checks", {}).get("contract_domain_count") == 20
        and bounded.get("checks", {}).get("all_contract_domains_passed") is True,
        "bounded contract coverage is incomplete",
    )
    _require(
        bounded.get("business_result", {}).get("actual") == {"gross_cents": 4595276, "orders": 500},
        "bounded business result differs",
    )
    executions = bounded.get("checks", {}).get("executions")
    _require(
        isinstance(executions, dict)
        and len(executions) == 8
        and all(
            isinstance(value, dict) and value.get("passed") is True for value in executions.values()
        ),
        "bounded execution outcomes are incomplete",
    )
    _require(bounded.get("metered_usage", {}).get("glue_job_runs") == 6, "Glue run count differs")

    _require(recovery_manifest.get("run_id") == STAGE6_RECOVERY_RUN_ID, "recovery run differs")
    _require(recovery.get("result") == "PASS", "recovery summary did not pass")
    for key, expected in {
        "claim_level": "AWS_VERIFIED",
        "cleanup_only": True,
        "workload_execution": False,
        "teardown_complete": True,
        "lease_released": True,
    }.items():
        _require(recovery.get(key) == expected, f"recovery {key} differs")

    _require(
        preflight_manifest.get("evidence_type") == "part4-stage7-final-read-only-preflight",
        "final preflight evidence type differs",
    )
    _require(preflight.get("result") == "PASS", "final preflight did not pass")
    _require(preflight.get("claim_level") == "AWS_VERIFIED", "final preflight claim differs")
    _require(preflight.get("source_commit") == control_commit, "final preflight source differs")
    _require(
        preflight_manifest.get("source_commit") == control_commit,
        "preflight manifest source differs",
    )
    _require(preflight.get("aws_mutation") is False, "final preflight mutated AWS")
    _require(preflight.get("workload_execution") is False, "final preflight started workload")
    _require(preflight.get("account_lease_absent") is True, "final preflight lease is present")
    _require(preflight.get("terraform_state_resources") == [], "final preflight state is not empty")
    _require(preflight.get("unexpected_resources") == [], "final preflight found active resources")
    _require(preflight.get("kms_inspection_error_count") == 0, "final KMS inspection failed")
    _require(preflight.get("pending_deletion_kms_alias_count") == 0, "KMS aliases remain")

    runtime = build_runtime_receipt(repository, paths=runtime_paths)
    _require(runtime["result"] == "PASS", "; ".join(runtime["errors"]))
    credit_path = repository / "evidence/aws/organization-shared-credit-baseline.json"
    credit = _load_object(credit_path)
    _require(credit.get("recipient_account_id") == EXPECTED_ACCOUNT, "credit recipient differs")
    _require(credit.get("credit_sharing_active") is True, "credit sharing is inactive")
    _require(
        credit.get("credit_level_cost_category_restriction") is False,
        "credit-level sharing is restricted",
    )
    _require(float(credit.get("verified_remaining_usd", 0)) >= 5, "verified credit is insufficient")
    observed_at = _timestamp(credit.get("observed_at"), "credit observed_at")
    valid_until = _timestamp(credit.get("valid_until"), "credit valid_until")
    preflight_created = _timestamp(
        preflight_manifest.get("artifact", {}).get("created_at"), "preflight artifact created_at"
    )
    _require(
        observed_at <= preflight_created <= valid_until,
        "credit evidence was not valid at preflight",
    )

    schema_path = repository / CLOSURE_SCHEMA
    manifest_path = repository / RUNTIME_MANIFEST
    sources: dict[str, str] = {}
    for directory in (bounded_directory, recovery_directory, preflight_directory):
        for path in sorted(directory.iterdir()):
            sources[path.relative_to(repository).as_posix()] = _sha256(path)
    sources[credit_path.relative_to(repository).as_posix()] = _sha256(credit_path)
    sources[manifest_path.relative_to(repository).as_posix()] = _sha256(manifest_path)

    payload: dict[str, Any] = {
        "actual_billed_cost_claim": "UNCLAIMED",
        "aws_execution": False,
        "claim_boundaries": {
            "production": "NOT_CLAIMED",
            "settled_billing": "UNCLAIMED",
            "sustained_operation": "NOT_ESTABLISHED",
        },
        "claim_level": "LOCAL_VERIFIED",
        "clean_inventory_authority": {
            "account_lease_absent": True,
            "aws_account_id": EXPECTED_ACCOUNT,
            "aws_region": EXPECTED_REGION,
            "claim_level": "AWS_VERIFIED",
            "run_id": int(preflight["run_id"]),
            "source_commit": control_commit,
            "terraform_state_resource_count": 0,
            "unexpected_resource_count": 0,
        },
        "closure_control_commit": control_commit,
        "errors": [],
        "evidence_type": "part4-stage7-project-closure",
        "financial_boundary": {
            "credit_expiration_date": credit["credit_expiration_date"],
            "credit_level_cost_category_restriction": False,
            "credit_sharing_active": True,
            "evidence_valid_until": credit["valid_until"],
            "owner_observed_at": credit["observed_at"],
            "verified_remaining_usd": float(credit["verified_remaining_usd"]),
        },
        "production_claim": False,
        "project": EXPECTED_PROJECT,
        "recovery_authority": {
            "claim_level": "AWS_VERIFIED",
            "cleanup_only": True,
            "lease_released": True,
            "run_id": STAGE6_RECOVERY_RUN_ID,
            "teardown_complete": True,
            "workload_execution": False,
        },
        "result": "PASS",
        "runtime_equivalence": {
            key: runtime[key]
            for key in ("baseline_source_commit", "file_count", "files_sha256", "result")
        },
        "schema_sha256": _sha256(schema_path),
        "schema_version": "1.0",
        "source_evidence_sha256": sources,
        "workload_authority": {
            "actual_gross_cents": 4595276,
            "actual_orders": 500,
            "claim_level": "AWS_VERIFIED",
            "contract_domain_count": 20,
            "glue_job_runs": 6,
            "run_id": STAGE6_BOUNDED_RUN_ID,
            "source_commit": STAGE6_SOURCE_COMMIT,
            "step_functions_executions": 8,
        },
    }
    return {**payload, "receipt_sha256": digest(payload)}


def validate_closure_receipt(
    receipt: dict[str, Any], repository: Path, *, runtime_paths: list[str] | None = None
) -> None:
    """Reject mutation, claim inflation, unknown keys, and schema drift."""

    expected_keys = {
        "actual_billed_cost_claim",
        "aws_execution",
        "claim_boundaries",
        "claim_level",
        "clean_inventory_authority",
        "closure_control_commit",
        "errors",
        "evidence_type",
        "financial_boundary",
        "production_claim",
        "project",
        "receipt_sha256",
        "recovery_authority",
        "result",
        "runtime_equivalence",
        "schema_sha256",
        "schema_version",
        "source_evidence_sha256",
        "workload_authority",
    }
    _require(set(receipt) == expected_keys, "closure receipt keys differ")
    supplied = receipt["receipt_sha256"]
    payload = dict(receipt)
    payload.pop("receipt_sha256")
    _require(supplied == digest(payload), "closure receipt digest differs")
    _require(receipt["result"] == "PASS" and receipt["errors"] == [], "closure did not pass")
    _require(receipt["claim_level"] == "LOCAL_VERIFIED", "closure claim level differs")
    _require(receipt["aws_execution"] is False, "closure falsely claims AWS execution")
    _require(receipt["production_claim"] is False, "closure falsely claims production")
    _require(receipt["actual_billed_cost_claim"] == "UNCLAIMED", "settled cost was claimed")
    _require(
        receipt["schema_sha256"] == _sha256(repository / CLOSURE_SCHEMA),
        "closure schema digest differs",
    )
    runtime = build_runtime_receipt(repository, paths=runtime_paths)
    expected_runtime = {
        key: runtime[key]
        for key in ("baseline_source_commit", "file_count", "files_sha256", "result")
    }
    _require(receipt["runtime_equivalence"] == expected_runtime, "runtime equivalence differs")
    _require(runtime["result"] == "PASS", "runtime equivalence did not pass")
    _require(
        receipt["workload_authority"].get("run_id") == STAGE6_BOUNDED_RUN_ID
        and receipt["workload_authority"].get("source_commit") == STAGE6_SOURCE_COMMIT,
        "workload authority differs",
    )
    _require(
        receipt["recovery_authority"].get("run_id") == STAGE6_RECOVERY_RUN_ID,
        "recovery authority differs",
    )
    sources = receipt["source_evidence_sha256"]
    _require(isinstance(sources, dict) and len(sources) == 14, "source evidence set differs")
    for relative, expected_digest in sources.items():
        _require(
            isinstance(relative, str)
            and isinstance(expected_digest, str)
            and SHA256_PATTERN.fullmatch(expected_digest) is not None,
            "source evidence digest entry is invalid",
        )
        path = repository / relative
        _require(path.is_file() and not path.is_symlink(), f"source evidence is absent: {relative}")
        _require(_sha256(path) == expected_digest, f"source evidence digest differs: {relative}")
