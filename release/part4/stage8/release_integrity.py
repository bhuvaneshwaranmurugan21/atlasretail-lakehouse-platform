"""Deterministic Part 4 Stage 8 release evidence and tag verification."""

from __future__ import annotations

import hashlib
import json
import re
import struct
import subprocess
import zlib
from pathlib import Path
from typing import Any, cast

from atlasretail.canonical import digest
from atlasretail.part4_stage7_closure import (
    RUNTIME_MANIFEST,
    build_runtime_receipt,
    validate_closure_receipt,
)

PROJECT = "AtlasRetail"
REPOSITORY = "bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform"
PACKAGE_VERSION = "0.1.0"
RELEASE_TAG = "v0.1.0"
STAGE7_COMMIT = "9ec723e2fa9cf27c6bc486132fd44100e9d30443"
STAGE7_TREE = "0fe8be70a87260aa5717606f32ae9581d7395912"
STAGE7_RECEIPT_SHA256 = "70fa1db23d9ea04f7f48a33103592975711ef364d882884a777b506ddde61ba8"
STAGE7_RECEIPT_FILE_SHA256 = "c42df8826a84d4049b81c05cd98ba4ae57aec09e927463751e6953d06b710bbf"
STAGE7_RUNTIME_SHA256 = "2e1d10c936c23637929e65589fab324c4a2602b98da283135527733ea26f1e38"
STAGE7_RUNTIME_FILE_COUNT = 107
SCHEMA = Path("release/part4/stage8/release.schema.json")
RETENTION_CATALOG = Path("release/part4/stage8/evidence-retention.json")
STAGE7_RECEIPT = Path("evidence/part4/stage7/completion-receipt.json")
RELEASE_RECEIPT = Path("evidence/part4/stage8/release-receipt.json")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_AUTHORITY_IDS = {
    "stage6-cleanup-recovery",
    "stage6-managed-workload",
    "stage7-final-clean-inventory",
    "stage7-project-closure",
}
EXPECTED_AUTHORITY_BINDINGS = {
    "stage6-cleanup-recovery": ("evidence/aws/recovery/33328391707", 33328391707),
    "stage6-managed-workload": ("evidence/aws/bounded/33329861907", 33329861907),
    "stage7-final-clean-inventory": ("evidence/aws/preflight/33364428199", 33364428199),
    "stage7-project-closure": (STAGE7_RECEIPT.as_posix(), None),
}


class ReleaseIntegrityError(ValueError):
    """Raised when release evidence is incomplete, mutable, or over-claimed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleaseIntegrityError(message)


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseIntegrityError(f"{path}: unreadable JSON: {error}") from error
    if not isinstance(value, dict):
        raise ReleaseIntegrityError(f"{path}: expected a JSON object")
    return value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _git(repository: Path, *arguments: str, binary: bool = False) -> str | bytes:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=repository,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReleaseIntegrityError(f"git {' '.join(arguments)} failed") from error
    if binary:
        return completed.stdout
    return completed.stdout.decode().strip()


def _require_commit(repository: Path, commit: str, label: str) -> None:
    _require(COMMIT_PATTERN.fullmatch(commit) is not None, f"{label} is not a full commit")
    resolved = _git(repository, "rev-parse", f"{commit}^{{commit}}")
    _require(resolved == commit, f"{label} is unavailable or ambiguous")


def _require_ancestor(repository: Path, ancestor: str, descendant: str, label: str) -> None:
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=repository,
        check=False,
        capture_output=True,
    )
    _require(completed.returncode == 0, label)


def _validate_external_artifact(value: object, authority_id: str) -> None:
    _require(isinstance(value, dict), f"{authority_id}: external artifact is absent")
    artifact = cast(dict[str, Any], value)
    expected = {"id", "name", "retention_days", "sha256", "state"}
    _require(set(artifact) == expected, f"{authority_id}: external artifact keys differ")
    _require(
        isinstance(artifact["id"], int) and artifact["id"] > 0,
        f"{authority_id}: external artifact ID is invalid",
    )
    _require(
        isinstance(artifact["name"], str) and bool(artifact["name"]),
        f"{authority_id}: external artifact name is invalid",
    )
    _require(artifact["retention_days"] == 30, f"{authority_id}: retention differs")
    _require(artifact["state"] == "EXPIRING", f"{authority_id}: artifact state differs")
    _require(
        isinstance(artifact["sha256"], str)
        and SHA256_PATTERN.fullmatch(artifact["sha256"]) is not None,
        f"{authority_id}: external artifact digest is invalid",
    )


def validate_retention_catalog(catalog: dict[str, Any], repository: Path) -> dict[str, int]:
    """Validate durable evidence coverage without requiring expiring raw artifacts."""

    expected_keys = {
        "authorities",
        "evidence_type",
        "policy",
        "project",
        "schema_version",
    }
    _require(set(catalog) == expected_keys, "retention catalog keys differ")
    _require(catalog["schema_version"] == "1.0", "retention schema version differs")
    _require(catalog["project"] == PROJECT, "retention project differs")
    _require(
        catalog["evidence_type"] == "part4-stage8-evidence-retention",
        "retention evidence type differs",
    )
    policy = catalog["policy"]
    _require(isinstance(policy, dict), "retention policy is absent")
    _require(
        set(policy)
        == {
            "credentials_committed",
            "durable_claims_require_raw_artifacts",
            "live_identifiers_committed",
            "raw_artifacts_committed",
        },
        "retention policy keys differ",
    )
    _require(
        policy
        == {
            "credentials_committed": False,
            "durable_claims_require_raw_artifacts": False,
            "live_identifiers_committed": False,
            "raw_artifacts_committed": False,
        },
        "retention policy permits unsafe or non-durable evidence",
    )
    authorities = catalog["authorities"]
    _require(isinstance(authorities, list), "retention authorities are absent")
    observed_ids: set[str] = set()
    external_count = 0
    for value in authorities:
        _require(isinstance(value, dict), "retention authority is not an object")
        authority = cast(dict[str, Any], value)
        expected = {
            "committed_path",
            "durable_form",
            "external_artifact",
            "id",
            "raw_artifact_required",
            "run_id",
        }
        _require(set(authority) == expected, "retention authority keys differ")
        authority_id = authority["id"]
        _require(isinstance(authority_id, str), "retention authority ID is invalid")
        _require(authority_id not in observed_ids, f"duplicate retention authority: {authority_id}")
        observed_ids.add(authority_id)
        _require(
            authority["durable_form"] in {"DIGEST_BOUND_SUMMARIES", "SELF_DIGESTING_RECEIPT"},
            f"{authority_id}: durable form differs",
        )
        _require(authority["raw_artifact_required"] is False, f"{authority_id}: raw data required")
        committed = authority["committed_path"]
        _require(
            isinstance(committed, str) and bool(committed),
            f"{authority_id}: path is invalid",
        )
        _require(".." not in Path(committed).parts, f"{authority_id}: path traversal is prohibited")
        path = repository / committed
        _require(
            path.exists() and not path.is_symlink(), f"{authority_id}: durable evidence absent"
        )
        run_id = authority["run_id"]
        expected_path, expected_run_id = EXPECTED_AUTHORITY_BINDINGS.get(authority_id, (None, None))
        _require(committed == expected_path, f"{authority_id}: committed path differs")
        _require(run_id == expected_run_id, f"{authority_id}: run ID differs")
        if authority_id == "stage7-project-closure":
            _require(run_id is None, "Stage 7 closure must not claim an execution run")
            _require(authority["external_artifact"] is None, "Stage 7 closure has raw artifact")
            _require(path.is_file(), "Stage 7 closure receipt is not a file")
        else:
            _require(isinstance(run_id, int) and run_id > 0, f"{authority_id}: run ID is invalid")
            _require(path.is_dir(), f"{authority_id}: committed evidence is not a directory")
            _validate_external_artifact(authority["external_artifact"], authority_id)
            manifest = _load_object(path / "manifest.json")
            _require(manifest.get("run_id") == run_id, f"{authority_id}: manifest run differs")
            manifest_artifact = manifest.get("artifact")
            external_artifact = authority["external_artifact"]
            _require(
                isinstance(manifest_artifact, dict) and isinstance(external_artifact, dict),
                f"{authority_id}: manifest artifact is absent",
            )
            manifest_artifact_map = cast(dict[str, Any], manifest_artifact)
            external_artifact_map = cast(dict[str, Any], external_artifact)
            for key in ("id", "name", "sha256"):
                _require(
                    external_artifact_map[key] == manifest_artifact_map.get(key),
                    f"{authority_id}: artifact {key} differs",
                )
            external_count += 1
    _require(observed_ids == EXPECTED_AUTHORITY_IDS, "retention authority coverage differs")
    return {
        "durable_authority_count": len(authorities),
        "external_expiring_artifact_count": external_count,
        "raw_artifact_required_count": 0,
    }


def _validate_stage7(repository: Path) -> dict[str, Any]:
    receipt_path = repository / STAGE7_RECEIPT
    _require(_sha256(receipt_path) == STAGE7_RECEIPT_FILE_SHA256, "Stage 7 receipt file differs")
    receipt = _load_object(receipt_path)
    validate_closure_receipt(receipt, repository)
    _require(receipt["receipt_sha256"] == STAGE7_RECEIPT_SHA256, "Stage 7 receipt digest differs")
    _require(receipt["aws_execution"] is False, "Stage 7 closure execution claim changed")
    _require(receipt["production_claim"] is False, "Stage 7 production claim changed")
    _require(
        receipt["actual_billed_cost_claim"] == "UNCLAIMED",
        "Stage 7 settled cost boundary changed",
    )
    return receipt


def build_release_receipt(repository: Path, controls_commit: str) -> dict[str, Any]:
    """Build deterministic release readiness bound to the merged controls commit."""

    _require_commit(repository, controls_commit, "release controls commit")
    _require_ancestor(
        repository,
        STAGE7_COMMIT,
        controls_commit,
        "release controls do not descend from Stage 7 closure",
    )
    head = _git(repository, "rev-parse", "HEAD")
    assert isinstance(head, str)
    _require_ancestor(
        repository,
        controls_commit,
        head,
        "current source does not descend from the release controls commit",
    )
    _require(
        _git(repository, "rev-parse", f"{STAGE7_COMMIT}^{{tree}}") == STAGE7_TREE,
        "Stage 7 tree differs",
    )
    _validate_stage7(repository)
    runtime = build_runtime_receipt(repository)
    _require(runtime["result"] == "PASS", "; ".join(runtime["errors"]))
    _require(runtime["file_count"] == STAGE7_RUNTIME_FILE_COUNT, "runtime file count differs")
    _require(runtime["files_sha256"] == STAGE7_RUNTIME_SHA256, "runtime digest differs")
    catalog_path = repository / RETENTION_CATALOG
    catalog = _load_object(catalog_path)
    retention = validate_retention_catalog(catalog, repository)
    schema_path = repository / SCHEMA
    _require(schema_path.is_file() and not schema_path.is_symlink(), "release schema is absent")
    sources = {
        STAGE7_RECEIPT.as_posix(): _sha256(repository / STAGE7_RECEIPT),
        RUNTIME_MANIFEST.as_posix(): _sha256(repository / RUNTIME_MANIFEST),
        RETENTION_CATALOG.as_posix(): _sha256(catalog_path),
        SCHEMA.as_posix(): _sha256(schema_path),
    }
    payload: dict[str, Any] = {
        "actual_billed_cost_claim": "UNCLAIMED",
        "aws_execution": False,
        "claim_boundaries": {
            "production": "NOT_CLAIMED",
            "settled_billing": "UNCLAIMED",
            "sustained_operation": "NOT_ESTABLISHED",
        },
        "claim_level": "LOCAL_VERIFIED",
        "controls_commit": controls_commit,
        "errors": [],
        "evidence_retention": {
            **retention,
            "catalog_sha256": _sha256(catalog_path),
            "result": "PASS",
        },
        "evidence_type": "part4-stage8-release-readiness",
        "predecessor": {
            "stage7_commit": STAGE7_COMMIT,
            "stage7_receipt_file_sha256": STAGE7_RECEIPT_FILE_SHA256,
            "stage7_receipt_sha256": STAGE7_RECEIPT_SHA256,
            "stage7_tree": STAGE7_TREE,
        },
        "production_claim": False,
        "project": PROJECT,
        "release": {
            "archive_format": "git-archive-tar-fixed-gzip-v1",
            "package_version": PACKAGE_VERSION,
            "signature_claim": "NOT_CLAIMED",
            "tag": RELEASE_TAG,
            "tag_target_state": "PENDING_FINAL_EVIDENCE_MERGE",
            "tag_type": "ANNOTATED",
        },
        "release_state": "READY_FOR_ANNOTATED_TAG",
        "result": "PASS",
        "runtime_equivalence": {
            key: runtime[key]
            for key in ("baseline_source_commit", "file_count", "files_sha256", "result")
        },
        "schema_sha256": _sha256(schema_path),
        "schema_version": "1.0",
        "source_evidence_sha256": sources,
    }
    return {**payload, "receipt_sha256": digest(payload)}


def validate_release_receipt(receipt: dict[str, Any], repository: Path) -> None:
    """Reject release drift, claim inflation, unknown keys, and non-determinism."""

    expected_keys = {
        "actual_billed_cost_claim",
        "aws_execution",
        "claim_boundaries",
        "claim_level",
        "controls_commit",
        "errors",
        "evidence_retention",
        "evidence_type",
        "predecessor",
        "production_claim",
        "project",
        "receipt_sha256",
        "release",
        "release_state",
        "result",
        "runtime_equivalence",
        "schema_sha256",
        "schema_version",
        "source_evidence_sha256",
    }
    _require(set(receipt) == expected_keys, "release receipt keys differ")
    supplied = receipt["receipt_sha256"]
    payload = dict(receipt)
    payload.pop("receipt_sha256")
    _require(supplied == digest(payload), "release receipt digest differs")
    _require(receipt["result"] == "PASS" and receipt["errors"] == [], "release readiness failed")
    _require(receipt["claim_level"] == "LOCAL_VERIFIED", "release claim level differs")
    _require(receipt["aws_execution"] is False, "release falsely claims AWS execution")
    _require(receipt["production_claim"] is False, "release falsely claims production")
    _require(receipt["actual_billed_cost_claim"] == "UNCLAIMED", "settled cost was claimed")
    _require(receipt["release_state"] == "READY_FOR_ANNOTATED_TAG", "release state differs")
    expected = build_release_receipt(repository, receipt["controls_commit"])
    _require(receipt == expected, "release receipt is stale or non-deterministic")


def fixed_gzip(value: bytes) -> bytes:
    """Return a gzip stream with fixed headers and deterministic deflate bytes."""

    compressor = zlib.compressobj(level=9, method=zlib.DEFLATED, wbits=-15)
    compressed = compressor.compress(value) + compressor.flush()
    header = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff"
    trailer = struct.pack("<II", zlib.crc32(value) & 0xFFFFFFFF, len(value) & 0xFFFFFFFF)
    return header + compressed + trailer


def build_release_archive(repository: Path, commit: str) -> bytes:
    """Build deterministic source bytes for the exact final release commit."""

    _require_commit(repository, commit, "release archive commit")
    prefix = f"atlasretail-lakehouse-platform-{PACKAGE_VERSION}/"
    archive = _git(
        repository,
        "archive",
        "--format=tar",
        f"--prefix={prefix}",
        commit,
        binary=True,
    )
    assert isinstance(archive, bytes)
    return fixed_gzip(archive)


def build_post_release_verification(
    repository: Path,
    tag: str,
    receipt_path: Path,
    archive_path: Path,
) -> dict[str, Any]:
    """Verify the annotated tag and deterministic archive after the evidence merge."""

    _require(tag == RELEASE_TAG, "release tag differs")
    object_type = _git(repository, "cat-file", "-t", tag)
    _require(object_type == "tag", "release tag is not annotated")
    target = _git(repository, "rev-parse", f"{tag}^{{commit}}")
    tag_object = _git(repository, "rev-parse", tag)
    assert isinstance(target, str) and isinstance(tag_object, str)
    _require_commit(repository, target, "release tag target")
    _require(_git(repository, "rev-parse", "HEAD") == target, "checkout is not the tag target")
    receipt_bytes = _git(repository, "show", f"{target}:{receipt_path.as_posix()}", binary=True)
    assert isinstance(receipt_bytes, bytes)
    receipt_value: object = json.loads(receipt_bytes)
    _require(isinstance(receipt_value, dict), "tagged release receipt is not an object")
    receipt = cast(dict[str, Any], receipt_value)
    validate_release_receipt(receipt, repository)
    committed_receipt_sha = _sha256_bytes(receipt_bytes)
    archive_bytes = archive_path.read_bytes()
    expected_archive = build_release_archive(repository, target)
    _require(archive_bytes == expected_archive, "release archive is not reproducible")
    archive_sha = _sha256_bytes(archive_bytes)
    tag_text = _git(repository, "cat-file", "-p", tag)
    assert isinstance(tag_text, str)
    required_lines = {
        f"Release-Commit: {target}",
        f"Release-Receipt-SHA256: {committed_receipt_sha}",
        f"Source-Archive-SHA256: {archive_sha}",
        "Signature-Claim: NOT_CLAIMED",
    }
    _require(required_lines.issubset(set(tag_text.splitlines())), "tag annotation bindings differ")
    payload: dict[str, Any] = {
        "archive_sha256": archive_sha,
        "claim_level": "LOCAL_VERIFIED",
        "evidence_type": "part4-stage8-post-release-verification",
        "production_claim": False,
        "project": PROJECT,
        "release_receipt_file_sha256": committed_receipt_sha,
        "release_receipt_sha256": receipt["receipt_sha256"],
        "result": "PASS",
        "schema_version": "1.0",
        "signature_claim": "NOT_CLAIMED",
        "tag": tag,
        "tag_object": tag_object,
        "tag_target_commit": target,
        "tag_type": "ANNOTATED",
    }
    return {**payload, "verification_sha256": digest(payload)}


def write_json(path: Path, value: dict[str, Any]) -> None:
    """Write canonical presentation JSON through an atomic same-directory replacement."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_bytes(path: Path, value: bytes) -> None:
    """Write release bytes through an atomic same-directory replacement."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(value)
    temporary.replace(path)
