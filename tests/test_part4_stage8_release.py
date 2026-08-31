"""Adversarial checks for Part 4 Stage 8 release integrity."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from atlasretail.canonical import digest
from release.part4.stage8.release_integrity import (
    RELEASE_RECEIPT,
    RELEASE_TAG,
    RETENTION_CATALOG,
    ReleaseIntegrityError,
    build_post_release_verification,
    build_release_archive,
    build_release_receipt,
    validate_release_receipt,
    validate_retention_catalog,
    write_bytes,
    write_json,
)
from release.part4.stage8.validate_controls import ControlsError, validate, validate_schema

ROOT = Path(__file__).parents[1]


def resign(receipt: dict[str, Any]) -> None:
    payload = dict(receipt)
    payload.pop("receipt_sha256")
    receipt["receipt_sha256"] = digest(payload)


def head(repository: Path = ROOT) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_stage8_controls_and_candidate_receipt_are_deterministic() -> None:
    first = validate(ROOT)
    second = validate(ROOT)
    assert first == second
    assert first["result"] == "PASS"
    assert first["claim_level"] == "LOCAL_VERIFIED"
    assert first["aws_execution"] is False
    assert first["production_claim"] is False
    assert first["actual_billed_cost_claim"] == "UNCLAIMED"
    assert first["runtime_equivalence"]["file_count"] == 107
    assert first["release_state"] in {"CONTROLS_READY", "READY_FOR_ANNOTATED_TAG"}
    assert all(first["checks"].values())

    receipt_one = build_release_receipt(ROOT, head())
    receipt_two = build_release_receipt(ROOT, head())
    assert receipt_one == receipt_two
    validate_release_receipt(receipt_one, ROOT)


def test_release_schema_cannot_permit_unknown_properties(tmp_path: Path) -> None:
    source = ROOT / "release/part4/stage8/release.schema.json"
    schema = json.loads(source.read_text(encoding="utf-8"))
    schema["additionalProperties"] = True
    path = tmp_path / "release.schema.json"
    path.write_text(json.dumps(schema), encoding="utf-8")
    with pytest.raises(ControlsError, match="permits unknown keys"):
        validate_schema(path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("aws_execution", True, "AWS execution"),
        ("production_claim", True, "production"),
        ("actual_billed_cost_claim", "CLAIMED", "settled cost"),
    ],
)
def test_release_receipt_rejects_claim_inflation(
    field: str,
    value: object,
    message: str,
) -> None:
    receipt = build_release_receipt(ROOT, head())
    receipt[field] = value
    resign(receipt)
    with pytest.raises(ReleaseIntegrityError, match=message):
        validate_release_receipt(receipt, ROOT)


def test_release_receipt_rejects_unknown_keys() -> None:
    receipt = build_release_receipt(ROOT, head())
    receipt["unexpected"] = True
    resign(receipt)
    with pytest.raises(ReleaseIntegrityError, match="keys differ"):
        validate_release_receipt(receipt, ROOT)


def test_release_receipt_rejects_digest_mutation() -> None:
    receipt = build_release_receipt(ROOT, head())
    receipt["receipt_sha256"] = "0" * 64
    with pytest.raises(ReleaseIntegrityError, match="digest differs"):
        validate_release_receipt(receipt, ROOT)


def test_retention_catalog_rejects_duplicate_authority() -> None:
    catalog = json.loads((ROOT / RETENTION_CATALOG).read_text(encoding="utf-8"))
    catalog["authorities"][1]["id"] = catalog["authorities"][0]["id"]
    with pytest.raises(ReleaseIntegrityError, match="duplicate retention authority"):
        validate_retention_catalog(catalog, ROOT)


def test_retention_catalog_rejects_raw_artifact_dependency() -> None:
    catalog = json.loads((ROOT / RETENTION_CATALOG).read_text(encoding="utf-8"))
    catalog["authorities"][0]["raw_artifact_required"] = True
    with pytest.raises(ReleaseIntegrityError, match="raw data required"):
        validate_retention_catalog(catalog, ROOT)


def test_retention_catalog_rejects_path_traversal() -> None:
    catalog = json.loads((ROOT / RETENTION_CATALOG).read_text(encoding="utf-8"))
    catalog["authorities"][0]["committed_path"] = "../outside"
    with pytest.raises(ReleaseIntegrityError, match="path traversal"):
        validate_retention_catalog(catalog, ROOT)


def test_archive_is_byte_deterministic() -> None:
    commit = head()
    first = build_release_archive(ROOT, commit)
    second = build_release_archive(ROOT, commit)
    assert first == second
    assert first[:10] == b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff"


def clone_with_controls(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "repository"
    subprocess.run(
        ["git", "clone", "--quiet", "--shared", str(ROOT), str(repository)],
        check=True,
    )
    shutil.copytree(ROOT / "release", repository / "release", dirs_exist_ok=True)
    shutil.copy2(ROOT / ".github/workflows/ci.yml", repository / ".github/workflows/ci.yml")
    shutil.copy2(ROOT / "Makefile", repository / "Makefile")
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.email", "release-test@example.invalid"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "add", "release", ".github/workflows/ci.yml", "Makefile"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "Add release controls"], cwd=repository, check=True
    )
    return repository, head(repository)


def prepare_tagged_release(tmp_path: Path, *, annotated: bool) -> tuple[Path, Path]:
    repository, controls_commit = clone_with_controls(tmp_path)
    receipt = build_release_receipt(repository, controls_commit)
    receipt_path = repository / RELEASE_RECEIPT
    write_json(receipt_path, receipt)
    subprocess.run(["git", "add", RELEASE_RECEIPT.as_posix()], cwd=repository, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "Publish release receipt"], cwd=repository, check=True
    )
    release_commit = head(repository)
    archive_path = tmp_path / "release.tar.gz"
    write_bytes(archive_path, build_release_archive(repository, release_commit))
    receipt_file_sha = subprocess.run(
        ["sha256sum", RELEASE_RECEIPT.as_posix()],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()[0]
    archive_sha = subprocess.run(
        ["sha256sum", str(archive_path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()[0]
    if annotated:
        message = "\n".join(
            (
                "AtlasRetail Lakehouse Platform v0.1.0",
                "",
                f"Release-Commit: {release_commit}",
                f"Release-Receipt-SHA256: {receipt_file_sha}",
                f"Source-Archive-SHA256: {archive_sha}",
                "Signature-Claim: NOT_CLAIMED",
            )
        )
        subprocess.run(
            ["git", "tag", "-a", RELEASE_TAG, release_commit, "-m", message],
            cwd=repository,
            check=True,
        )
    else:
        subprocess.run(["git", "tag", RELEASE_TAG, release_commit], cwd=repository, check=True)
    return repository, archive_path


def test_annotated_tag_and_archive_verify(tmp_path: Path) -> None:
    repository, archive = prepare_tagged_release(tmp_path, annotated=True)
    verification = build_post_release_verification(
        repository,
        RELEASE_TAG,
        RELEASE_RECEIPT,
        archive,
    )
    assert verification["result"] == "PASS"
    assert verification["tag_type"] == "ANNOTATED"
    assert verification["signature_claim"] == "NOT_CLAIMED"


def test_lightweight_tag_is_rejected(tmp_path: Path) -> None:
    repository, archive = prepare_tagged_release(tmp_path, annotated=False)
    with pytest.raises(ReleaseIntegrityError, match="not annotated"):
        build_post_release_verification(
            repository,
            RELEASE_TAG,
            RELEASE_RECEIPT,
            archive,
        )
