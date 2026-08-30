"""Fail-closed admission for Part 4 managed-execution prerequisites."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canonical import digest
from .terraform_envelope import EXPECTED_DATA_ADDRESSES, EXPECTED_MANAGED_ADDRESSES

EXPECTED_ACCOUNT = "857229544428"
EXPECTED_REGION = "ap-southeast-2"
EXPECTED_ROLE = f"arn:aws:iam::{EXPECTED_ACCOUNT}:role/AtlasRetailGitHubOidcRole"
EXPECTED_PROJECT = "AtlasRetail"
EXPECTED_STATE_KEY = "atlasretail/main.tfstate"
PREREQUISITE_SCHEMA_RELATIVE_PATH = Path(
    "contracts/part4/stage6-prerequisite-admission.schema.json"
)
RUN_ID_PATTERN = re.compile(r"^[1-9][0-9]*$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class PrerequisiteError(ValueError):
    """Raised when managed-execution prerequisites are incomplete or stale."""


@dataclass(frozen=True)
class PrerequisiteContext:
    """Exact source and workflow identities required of all prerequisite runs."""

    source_commit: str
    repository: str
    ref: str
    preflight_run_id: str
    glue_probe_run_id: str
    plan_run_id: str


def _load(root: Path, name: str, errors: list[str]) -> dict[str, Any]:
    path = root / name
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"{root.name}/{name}: {error}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{root.name}/{name}: expected a JSON object")
        return {}
    return value


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def _identity(
    value: dict[str, Any],
    *,
    context: PrerequisiteContext,
    run_id: str,
    label: str,
    errors: list[str],
) -> None:
    expected = {
        "aws_account_id": EXPECTED_ACCOUNT,
        "aws_region": EXPECTED_REGION,
        "github_run_id": run_id,
        "oidc_role_arn": EXPECTED_ROLE,
        "project": EXPECTED_PROJECT,
        "ref": context.ref,
        "repository": context.repository,
        "result": "PASS",
        "run_ceiling_usd": 5,
        "schema_version": "1.0",
        "source_commit": context.source_commit,
        "terraform_state_key": EXPECTED_STATE_KEY,
    }
    _require(value == expected, f"{label} source identity mismatch", errors)


def _manifest(root: Path, errors: list[str]) -> dict[str, str]:
    if not root.is_dir():
        errors.append(f"{root}: prerequisite directory is absent")
        return {}
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            errors.append(f"{root.name}/{relative}: symbolic links are prohibited")
            continue
        if path.is_dir():
            continue
        if not path.is_file():
            errors.append(f"{root.name}/{relative}: non-regular entry is prohibited")
            continue
        result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not result:
        errors.append(f"{root.name}: prerequisite artifact is empty")
    return result


def build_prerequisite_receipt(
    *,
    preflight_dir: Path,
    glue_probe_dir: Path,
    plan_dir: Path,
    context: PrerequisiteContext,
    schema_path: Path | None = None,
) -> dict[str, Any]:
    """Validate all three artifacts and return their deterministic binding receipt."""

    errors: list[str] = []
    resolved_schema = (
        schema_path
        if schema_path is not None
        else Path(__file__).resolve().parents[2] / PREREQUISITE_SCHEMA_RELATIVE_PATH
    )
    try:
        schema_sha256 = hashlib.sha256(resolved_schema.read_bytes()).hexdigest()
    except OSError as error:
        errors.append(f"prerequisite schema is unreadable: {error}")
        schema_sha256 = "0" * 64
    _require(
        COMMIT_PATTERN.fullmatch(context.source_commit) is not None, "invalid source commit", errors
    )
    for label, run_id in (
        ("preflight", context.preflight_run_id),
        ("Glue probe", context.glue_probe_run_id),
        ("plan", context.plan_run_id),
    ):
        _require(RUN_ID_PATTERN.fullmatch(run_id) is not None, f"invalid {label} run ID", errors)

    manifests = {
        "read_only_preflight": _manifest(preflight_dir, errors),
        "glue_capability_probe": _manifest(glue_probe_dir, errors),
        "plan_only_proof": _manifest(plan_dir, errors),
    }

    preflight_identity = _load(preflight_dir, "source-identity.json", errors)
    _identity(
        preflight_identity,
        context=context,
        run_id=context.preflight_run_id,
        label="preflight",
        errors=errors,
    )
    preflight = _load(preflight_dir, "preflight.json", errors)
    _require(preflight.get("result") == "PASS", "preflight did not pass", errors)
    _require(
        preflight.get("terraform_state_resources") == [], "preflight state is not empty", errors
    )
    _require(
        preflight.get("unexpected_resources") == [], "preflight found active resources", errors
    )
    _require(preflight.get("errors") == [], "preflight contains errors", errors)

    glue_identity = _load(glue_probe_dir, "source-identity.json", errors)
    _identity(
        glue_identity,
        context=context,
        run_id=context.glue_probe_run_id,
        label="Glue probe",
        errors=errors,
    )
    glue = _load(glue_probe_dir, "phase-4-summary.json", errors)
    _require(glue.get("result") == "PASS", "Glue capability probe did not pass", errors)
    _require(
        glue.get("claim") == "AWS_GLUE_DEFINITION_CAPABILITY_VERIFIED",
        "Glue capability claim mismatch",
        errors,
    )
    _require(
        glue.get("source_commit") == context.source_commit, "Glue probe source mismatch", errors
    )
    _require(
        str(glue.get("run_id")) == context.glue_probe_run_id, "Glue probe run mismatch", errors
    )
    _require(
        glue.get("workload_started") is False, "Glue probe workload-start proof is absent", errors
    )
    _require(
        glue.get("aws_verified", {}).get("independent_cleanup") is True,
        "Glue probe independent cleanup is absent",
        errors,
    )

    plan_identity = _load(plan_dir, "source-identity.json", errors)
    _identity(
        plan_identity,
        context=context,
        run_id=context.plan_run_id,
        label="plan",
        errors=errors,
    )
    plan_summary = _load(plan_dir, "summary.json", errors)
    plan_validation = _load(plan_dir, "terraform-plan-validation.json", errors)
    no_change = _load(plan_dir, "no-change-verification.json", errors)
    _require(plan_summary.get("result") == "PASS", "plan summary did not pass", errors)
    _require(
        plan_summary.get("source_commit") == context.source_commit, "plan source mismatch", errors
    )
    _require(
        str(plan_summary.get("github_run_id")) == context.plan_run_id, "plan run mismatch", errors
    )
    _require(plan_validation.get("result") == "PASS", "plan validation did not pass", errors)
    _require(
        plan_validation.get("exact_envelope") is True,
        "plan exact envelope was not enforced",
        errors,
    )
    _require(
        plan_validation.get("resource_count") == len(EXPECTED_MANAGED_ADDRESSES),
        "plan managed count mismatch",
        errors,
    )
    _require(
        plan_validation.get("read_only_data_source_counts")
        == {"aws_iam_policy_document": len(EXPECTED_DATA_ADDRESSES)},
        "plan data-source count mismatch",
        errors,
    )
    _require(no_change.get("result") == "PASS", "plan no-change proof did not pass", errors)

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "proof": "part4-stage6-managed-execution-prerequisites",
        "project": EXPECTED_PROJECT,
        "source_identity": {
            "repository": context.repository,
            "ref": context.ref,
            "source_commit": context.source_commit,
        },
        "prerequisite_runs": {
            "read_only_preflight": context.preflight_run_id,
            "glue_capability_probe": context.glue_probe_run_id,
            "plan_only_proof": context.plan_run_id,
        },
        "artifact_manifests": manifests,
        "validations": {
            "clean_preflight": preflight.get("result") == "PASS" and not errors,
            "glue_create_delete": glue.get("result") == "PASS" and not errors,
            "exact_plan": plan_validation.get("result") == "PASS" and not errors,
        },
        "result": "PASS" if not errors else "FAIL",
        "schema_sha256": schema_sha256,
        "errors": errors,
    }
    return {**payload, "receipt_sha256": digest(payload)}


def validate_prerequisite_receipt(
    receipt: dict[str, Any], *, schema_path: Path | None = None
) -> None:
    """Validate the strict self-digesting receipt shape before it is rebound."""

    expected_keys = {
        "artifact_manifests",
        "errors",
        "prerequisite_runs",
        "project",
        "proof",
        "receipt_sha256",
        "result",
        "schema_sha256",
        "schema_version",
        "source_identity",
        "validations",
    }
    if set(receipt) != expected_keys:
        raise PrerequisiteError("prerequisite receipt keys differ")
    supplied = receipt.get("receipt_sha256")
    payload = dict(receipt)
    payload.pop("receipt_sha256", None)
    if supplied != digest(payload):
        raise PrerequisiteError("prerequisite receipt digest differs")
    if receipt.get("result") != "PASS" or receipt.get("errors") != []:
        raise PrerequisiteError("prerequisite receipt did not pass")
    if receipt.get("proof") != "part4-stage6-managed-execution-prerequisites":
        raise PrerequisiteError("prerequisite receipt proof differs")
    runs = receipt.get("prerequisite_runs")
    if not isinstance(runs, dict) or set(runs) != {
        "read_only_preflight",
        "glue_capability_probe",
        "plan_only_proof",
    }:
        raise PrerequisiteError("prerequisite run bindings differ")
    if any(
        not isinstance(value, str) or RUN_ID_PATTERN.fullmatch(value) is None
        for value in runs.values()
    ):
        raise PrerequisiteError("prerequisite run binding is invalid")
    if receipt.get("schema_version") != "1.0" or receipt.get("project") != EXPECTED_PROJECT:
        raise PrerequisiteError("prerequisite receipt identity differs")
    schema_sha256 = receipt.get("schema_sha256")
    if not isinstance(schema_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", schema_sha256) is None:
        raise PrerequisiteError("prerequisite schema digest is invalid")
    resolved_schema = (
        schema_path
        if schema_path is not None
        else Path(__file__).resolve().parents[2] / PREREQUISITE_SCHEMA_RELATIVE_PATH
    )
    try:
        expected_schema_sha256 = hashlib.sha256(resolved_schema.read_bytes()).hexdigest()
    except OSError as error:
        raise PrerequisiteError(f"prerequisite schema is unreadable: {error}") from error
    if schema_sha256 != expected_schema_sha256:
        raise PrerequisiteError("prerequisite schema digest differs")
    identity = receipt.get("source_identity")
    if not isinstance(identity, dict) or set(identity) != {"ref", "repository", "source_commit"}:
        raise PrerequisiteError("prerequisite source identity differs")
    if (
        identity.get("ref") != "refs/heads/main"
        or identity.get("repository") != "bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform"
        or not isinstance(identity.get("source_commit"), str)
        or COMMIT_PATTERN.fullmatch(identity["source_commit"]) is None
    ):
        raise PrerequisiteError("prerequisite source identity is invalid")
    if receipt.get("validations") != {
        "clean_preflight": True,
        "exact_plan": True,
        "glue_create_delete": True,
    }:
        raise PrerequisiteError("prerequisite validations are incomplete")
    manifests = receipt.get("artifact_manifests")
    if not isinstance(manifests, dict) or set(manifests) != set(runs):
        raise PrerequisiteError("prerequisite artifact manifests differ")
    for name, manifest in manifests.items():
        if not isinstance(manifest, dict) or not manifest:
            raise PrerequisiteError(f"prerequisite artifact manifest is empty: {name}")
        for relative, sha256 in manifest.items():
            path = Path(relative)
            if (
                not isinstance(relative, str)
                or path.is_absolute()
                or ".." in path.parts
                or not isinstance(sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", sha256) is None
            ):
                raise PrerequisiteError(f"prerequisite artifact manifest entry is invalid: {name}")


def load_prerequisite_receipt(path: Path, *, schema_path: Path | None = None) -> dict[str, Any]:
    """Load and validate one persisted prerequisite receipt."""

    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PrerequisiteError(f"prerequisite receipt is unreadable: {error}") from error
    if not isinstance(value, dict):
        raise PrerequisiteError("prerequisite receipt must be a JSON object")
    validate_prerequisite_receipt(value, schema_path=schema_path)
    return value
