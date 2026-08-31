"""Adversarial tests for Part 4 Stage 7 closure evidence."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from atlasretail.canonical import digest
from atlasretail.part4_stage7_closure import (
    STAGE6_BOUNDED_RUN_ID,
    STAGE6_RECOVERY_RUN_ID,
    ClosureError,
    build_closure_receipt,
    build_runtime_receipt,
    load_runtime_manifest,
    publish_preflight_evidence,
    tracked_runtime_paths,
    validate_closure_receipt,
)

ROOT = Path(__file__).parents[1]
CONTROL_COMMIT = "a" * 40
RUN_ID = 44444444444


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination)


def fixture_repository(tmp_path: Path) -> tuple[Path, list[str], Path]:
    manifest = load_runtime_manifest(ROOT / "contracts/part4/stage7-runtime-manifest.json")
    paths = tracked_runtime_paths(ROOT, manifest)
    for relative in paths:
        copy_file(ROOT / relative, tmp_path / relative)
    for relative in (
        "contracts/part4/stage7-runtime-manifest.json",
        "contracts/part4/stage7-closure.schema.json",
        "evidence/aws/organization-shared-credit-baseline.json",
    ):
        copy_file(ROOT / relative, tmp_path / relative)
    copy_tree(
        ROOT / f"evidence/aws/bounded/{STAGE6_BOUNDED_RUN_ID}",
        tmp_path / f"evidence/aws/bounded/{STAGE6_BOUNDED_RUN_ID}",
    )
    copy_tree(
        ROOT / f"evidence/aws/recovery/{STAGE6_RECOVERY_RUN_ID}",
        tmp_path / f"evidence/aws/recovery/{STAGE6_RECOVERY_RUN_ID}",
    )

    raw = tmp_path / "raw-preflight"
    write(
        raw / "source-identity.json",
        {
            "aws_account_id": "857229544428",
            "aws_region": "ap-southeast-2",
            "github_run_id": str(RUN_ID),
            "oidc_role_arn": "arn:aws:iam::857229544428:role/AtlasRetailGitHubOidcRole",
            "project": "AtlasRetail",
            "ref": "refs/heads/main",
            "repository": "bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform",
            "result": "PASS",
            "run_ceiling_usd": 5,
            "schema_version": "1.0",
            "source_commit": CONTROL_COMMIT,
            "terraform_state_key": "atlasretail/main.tfstate",
        },
    )
    write(
        raw / "preflight.json",
        {
            "account_lease_absent": True,
            "errors": [],
            "kms_inspection_errors": [],
            "pending_deletion_kms_aliases": [],
            "pending_deletion_kms_keys": [
                {"KeyId": "sensitive-live-key-id", "Arn": "sensitive-live-key-arn"}
            ],
            "result": "PASS",
            "terraform_state_resources": [],
            "unexpected_resources": [],
        },
    )
    write(
        raw / "account-plan-verification.json",
        {
            "credit_source": "organization-shared",
            "organization_shared_credit_usd": 119.22,
            "result": "PASS",
        },
    )
    preflight = tmp_path / f"evidence/aws/preflight/{RUN_ID}"
    publish_preflight_evidence(
        raw_directory=raw,
        output_directory=preflight,
        artifact={
            "created_at": "2026-08-31T06:00:00Z",
            "id": 9999999999,
            "name": f"atlasretail-read-only-preflight-{RUN_ID}",
            "sha256": "b" * 64,
            "size_bytes": 4096,
        },
    )
    return tmp_path, paths, preflight


def build(tmp_path: Path) -> tuple[dict[str, Any], Path, list[str]]:
    repository, paths, preflight = fixture_repository(tmp_path)
    receipt = build_closure_receipt(
        repository=repository,
        bounded_directory=repository / f"evidence/aws/bounded/{STAGE6_BOUNDED_RUN_ID}",
        recovery_directory=repository / f"evidence/aws/recovery/{STAGE6_RECOVERY_RUN_ID}",
        preflight_directory=preflight,
        control_commit=CONTROL_COMMIT,
        runtime_paths=paths,
    )
    return receipt, repository, paths


def resign(receipt: dict[str, Any]) -> None:
    payload = dict(receipt)
    payload.pop("receipt_sha256")
    receipt["receipt_sha256"] = digest(payload)


def test_runtime_surface_matches_the_frozen_stage6_bytes() -> None:
    first = build_runtime_receipt(ROOT)
    second = build_runtime_receipt(ROOT)
    assert first == second
    assert first == {
        "baseline_source_commit": "08559b0f48708080335282c6d59faa3826635d67",
        "errors": [],
        "file_count": 107,
        "files_sha256": "2e1d10c936c23637929e65589fab324c4a2602b98da283135527733ea26f1e38",
        "result": "PASS",
    }


def test_runtime_byte_drift_is_rejected(tmp_path: Path) -> None:
    repository, paths, _ = fixture_repository(tmp_path)
    changed = repository / paths[0]
    changed.write_bytes(changed.read_bytes() + b"\nunauthorized runtime drift\n")
    result = build_runtime_receipt(repository, paths=paths)
    assert result["result"] == "FAIL"
    assert result["errors"] == ["runtime bytes differ from the frozen Stage 6 surface"]


def test_runtime_addition_and_omission_are_rejected(tmp_path: Path) -> None:
    repository, paths, _ = fixture_repository(tmp_path)
    added = "src/atlasretail/unauthorized_runtime.py"
    (repository / added).write_text("VALUE = 1\n", encoding="utf-8")
    addition = build_runtime_receipt(repository, paths=[*paths, added])
    omission = build_runtime_receipt(repository, paths=paths[1:])
    assert addition["result"] == "FAIL"
    assert omission["result"] == "FAIL"
    assert "runtime file count differs" in addition["errors"][0]
    assert "runtime file count differs" in omission["errors"][0]


def test_sanitized_preflight_and_closure_are_deterministic(tmp_path: Path) -> None:
    receipt, repository, paths = build(tmp_path)
    validate_closure_receipt(receipt, repository, runtime_paths=paths)
    second = build_closure_receipt(
        repository=repository,
        bounded_directory=repository / f"evidence/aws/bounded/{STAGE6_BOUNDED_RUN_ID}",
        recovery_directory=repository / f"evidence/aws/recovery/{STAGE6_RECOVERY_RUN_ID}",
        preflight_directory=repository / f"evidence/aws/preflight/{RUN_ID}",
        control_commit=CONTROL_COMMIT,
        runtime_paths=paths,
    )
    assert receipt == second
    committed = json.dumps(
        {
            path.name: path.read_text(encoding="utf-8")
            for path in (repository / f"evidence/aws/preflight/{RUN_ID}").iterdir()
        }
    )
    assert "sensitive-live-key-id" not in committed
    assert "sensitive-live-key-arn" not in committed
    assert receipt["claim_level"] == "LOCAL_VERIFIED"
    assert receipt["aws_execution"] is False
    assert receipt["production_claim"] is False
    assert receipt["actual_billed_cost_claim"] == "UNCLAIMED"
    assert len(receipt["source_evidence_sha256"]) == 14


def test_resigned_claim_inflation_is_rejected(tmp_path: Path) -> None:
    receipt, repository, paths = build(tmp_path)
    receipt["production_claim"] = True
    resign(receipt)
    with pytest.raises(ClosureError, match="falsely claims production"):
        validate_closure_receipt(receipt, repository, runtime_paths=paths)


def test_resigned_authority_mutation_is_rejected(tmp_path: Path) -> None:
    receipt, repository, paths = build(tmp_path)
    receipt["workload_authority"]["run_id"] = 1
    resign(receipt)
    with pytest.raises(ClosureError, match="workload authority differs"):
        validate_closure_receipt(receipt, repository, runtime_paths=paths)


def test_source_evidence_byte_mutation_is_rejected(tmp_path: Path) -> None:
    receipt, repository, paths = build(tmp_path)
    summary = repository / f"evidence/aws/bounded/{STAGE6_BOUNDED_RUN_ID}/summary.json"
    summary.write_bytes(summary.read_bytes() + b"\n")
    with pytest.raises(ClosureError, match="source evidence digest differs"):
        validate_closure_receipt(receipt, repository, runtime_paths=paths)


def test_preflight_outside_credit_validity_is_rejected(tmp_path: Path) -> None:
    repository, paths, preflight = fixture_repository(tmp_path)
    manifest = json.loads((preflight / "manifest.json").read_text(encoding="utf-8"))
    manifest["artifact"]["created_at"] = "2026-09-08T00:00:00Z"
    write(preflight / "manifest.json", manifest)
    with pytest.raises(ClosureError, match="credit evidence was not valid"):
        build_closure_receipt(
            repository=repository,
            bounded_directory=repository / f"evidence/aws/bounded/{STAGE6_BOUNDED_RUN_ID}",
            recovery_directory=repository / f"evidence/aws/recovery/{STAGE6_RECOVERY_RUN_ID}",
            preflight_directory=preflight,
            control_commit=CONTROL_COMMIT,
            runtime_paths=paths,
        )


def test_dirty_raw_preflight_cannot_be_published(tmp_path: Path) -> None:
    _, _, _ = fixture_repository(tmp_path)
    raw = tmp_path / "raw-preflight"
    preflight = json.loads((raw / "preflight.json").read_text(encoding="utf-8"))
    preflight["unexpected_resources"] = ["unexpected-live-resource"]
    write(raw / "preflight.json", preflight)
    with pytest.raises(ClosureError, match="unexpected active resources"):
        publish_preflight_evidence(
            raw_directory=raw,
            output_directory=tmp_path / "rejected",
            artifact={
                "created_at": "2026-08-31T06:00:00Z",
                "id": 1,
                "name": "artifact",
                "sha256": "b" * 64,
                "size_bytes": 1,
            },
        )
