from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from atlasretail.canonical import digest
from atlasretail.part4_admission import (
    ADMISSION_SCHEMA_RELATIVE_PATH,
    AdmissionContext,
    AdmissionError,
    build_admission_receipt,
    load_receipt,
    validate_admission_schema_file,
    verify_admission_receipt,
    write_receipt,
)
from atlasretail.provenance import materialize_part4_sources

ROOT = Path(__file__).parents[1]
COMMIT = "a" * 40


@pytest.fixture(scope="module")
def source_directory(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("part4-admission") / "sources"
    materialize_part4_sources(
        output,
        repo_root=ROOT,
        order_count=100,
        source_commit=COMMIT,
        run_id="123",
    )
    return output


@pytest.fixture()
def prerequisite_receipt(tmp_path: Path) -> Path:
    payload = {
        "artifact_manifests": {
            "glue_capability_probe": {"summary.json": "1" * 64},
            "plan_only_proof": {"summary.json": "2" * 64},
            "read_only_preflight": {"summary.json": "3" * 64},
        },
        "errors": [],
        "prerequisite_runs": {
            "glue_capability_probe": "102",
            "plan_only_proof": "103",
            "read_only_preflight": "101",
        },
        "project": "AtlasRetail",
        "proof": "part4-stage6-managed-execution-prerequisites",
        "result": "PASS",
        "schema_sha256": hashlib.sha256(
            (ROOT / "contracts/part4/stage6-prerequisite-admission.schema.json").read_bytes()
        ).hexdigest(),
        "schema_version": "1.0",
        "source_identity": {
            "ref": "refs/heads/main",
            "repository": "bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform",
            "source_commit": COMMIT,
        },
        "validations": {
            "clean_preflight": True,
            "exact_plan": True,
            "glue_create_delete": True,
        },
    }
    path = tmp_path / "prerequisite-admission.json"
    path.write_text(json.dumps({**payload, "receipt_sha256": digest(payload)}), encoding="utf-8")
    return path


@pytest.fixture()
def context(prerequisite_receipt: Path) -> AdmissionContext:
    return AdmissionContext(
        repository="bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform",
        workflow_name="AWS bounded lab",
        event="workflow_dispatch",
        ref="refs/heads/main",
        actor="bhuvaneshwaranmurugan21",
        repository_owner="bhuvaneshwaranmurugan21",
        source_commit=COMMIT,
        checked_out_commit=COMMIT,
        run_id="123",
        run_attempt="1",
        order_count="100",
        budget_ceiling_usd="5",
        confirm_execute="EXECUTE_ATLASRETAIL_PART4",
        confirm_destroy="DESTROY",
        prerequisite_receipt=prerequisite_receipt,
    )


def test_builds_and_revalidates_exact_admission(
    source_directory: Path, context: AdmissionContext
) -> None:
    receipt = build_admission_receipt(
        repo_root=ROOT, source_directory=source_directory, context=context
    )
    assert receipt["result"] == "PASS"
    assert receipt["workflow"]["run_attempt"] == "1"
    assert receipt["bounds"] == {
        "budget_ceiling_usd": 5,
        "order_count": 100,
        "runtime_expansion_prohibited": True,
    }
    assert (
        receipt["sources"]["source_provenance_summary_sha256"]
        != receipt["sources"]["source_provenance_summary_file_sha256"]
    )
    assert receipt["sources"]["file_count"] == 48
    assert receipt["sources"]["source_bytes"] > 0
    assert (
        verify_admission_receipt(
            receipt, repo_root=ROOT, source_directory=source_directory, context=context
        )
        == receipt
    )


def test_run_attempt_changes_receipt_not_source_tree(
    source_directory: Path, context: AdmissionContext
) -> None:
    first = build_admission_receipt(
        repo_root=ROOT, source_directory=source_directory, context=context
    )
    second = build_admission_receipt(
        repo_root=ROOT,
        source_directory=source_directory,
        context=replace(context, run_attempt="2"),
    )
    assert first["receipt_sha256"] != second["receipt_sha256"]
    assert first["sources"]["source_tree_sha256"] == second["sources"]["source_tree_sha256"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("repository", "other/repository"),
        ("workflow_name", "Another workflow"),
        ("event", "push"),
        ("ref", "refs/heads/feature"),
        ("actor", "another-operator"),
        ("repository_owner", "another-owner"),
        ("source_commit", "A" * 40),
        ("checked_out_commit", "b" * 40),
        ("run_id", "0"),
        ("run_attempt", "01"),
        ("order_count", "99"),
        ("order_count", "2001"),
        ("order_count", "100.0"),
        ("order_count", " 100"),
        ("budget_ceiling_usd", "0"),
        ("budget_ceiling_usd", "6"),
        ("budget_ceiling_usd", "5.0"),
        ("budget_ceiling_usd", "05"),
        ("confirm_execute", "execute_atlasretail_part4"),
        ("confirm_destroy", "DESTROY "),
    ],
)
def test_rejects_unadmitted_context(
    source_directory: Path,
    context: AdmissionContext,
    field: str,
    value: str,
) -> None:
    with pytest.raises(AdmissionError):
        build_admission_receipt(
            repo_root=ROOT,
            source_directory=source_directory,
            context=replace(context, **{field: value}),
        )


def test_rejects_receipt_mutation(source_directory: Path, context: AdmissionContext) -> None:
    receipt = build_admission_receipt(
        repo_root=ROOT, source_directory=source_directory, context=context
    )
    receipt["bounds"]["budget_ceiling_usd"] = 4
    with pytest.raises(AdmissionError, match="receipt.receipt_sha256"):
        verify_admission_receipt(
            receipt, repo_root=ROOT, source_directory=source_directory, context=context
        )


def test_rejects_receipt_for_stale_attempt(
    source_directory: Path, context: AdmissionContext
) -> None:
    receipt = build_admission_receipt(
        repo_root=ROOT, source_directory=source_directory, context=context
    )
    with pytest.raises(AdmissionError, match="receipt"):
        verify_admission_receipt(
            receipt,
            repo_root=ROOT,
            source_directory=source_directory,
            context=replace(context, run_attempt="2"),
        )


def test_rejects_changed_source_bytes(
    tmp_path: Path, source_directory: Path, context: AdmissionContext
) -> None:
    changed = tmp_path / "sources"
    shutil.copytree(source_directory, changed)
    target = next((changed / "success" / "orders").glob("*.jsonl.gz"))
    target.write_bytes(target.read_bytes() + b"changed")
    with pytest.raises(AdmissionError):
        build_admission_receipt(repo_root=ROOT, source_directory=changed, context=context)


def test_rejects_extra_source_file(
    tmp_path: Path, source_directory: Path, context: AdmissionContext
) -> None:
    changed = tmp_path / "sources"
    shutil.copytree(source_directory, changed)
    (changed / "undeclared.txt").write_text("not admitted", encoding="utf-8")
    with pytest.raises(AdmissionError, match="sources.root_files"):
        build_admission_receipt(repo_root=ROOT, source_directory=changed, context=context)


def test_rejects_symlinked_source(
    tmp_path: Path, source_directory: Path, context: AdmissionContext
) -> None:
    changed = tmp_path / "sources"
    shutil.copytree(source_directory, changed)
    (changed / "success" / "link").symlink_to(changed / "success" / "manifest.json")
    with pytest.raises(AdmissionError):
        build_admission_receipt(repo_root=ROOT, source_directory=changed, context=context)


def test_schema_is_strict_and_byte_bound(tmp_path: Path) -> None:
    schema = ROOT / ADMISSION_SCHEMA_RELATIVE_PATH
    digest = validate_admission_schema_file(schema)
    assert len(digest) == 64
    changed = json.loads(schema.read_text(encoding="utf-8"))
    changed["additionalProperties"] = True
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(AdmissionError, match="additionalProperties"):
        validate_admission_schema_file(path)


def test_receipt_round_trip(
    tmp_path: Path, source_directory: Path, context: AdmissionContext
) -> None:
    receipt = build_admission_receipt(
        repo_root=ROOT, source_directory=source_directory, context=context
    )
    path = tmp_path / "admission.json"
    write_receipt(path, receipt)
    assert load_receipt(path) == receipt
    path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(AdmissionError, match="JSON object"):
        load_receipt(path)
