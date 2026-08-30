"""Regression tests for independent Part 4 teardown-authority validation."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "validate_part4_teardown_authority",
    ROOT / "scripts/validate_part4_teardown_authority.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_validator_reads_contract_identity_from_validated_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = {"contract_id": "atlasretail-part4", "version": "1.0"}
    files = {
        "contracts/part4/run-contract.json": json.dumps(contract),
        ".github/atlas-target.json": "{}",
        "contracts/part4/teardown-authority.schema.json": "{}",
        "infra/atlas/.terraform.lock.hcl": "lock",
        "authority.json": '{"terraform": {}}',
        "admission.json": "{}",
        "plan.json": "{}",
        "plan.bin": "plan",
        "plan-validation.json": "{}",
    }
    for name, contents in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    authority_path = tmp_path / "authority.json"
    admission_path = tmp_path / "admission.json"
    validation_path = tmp_path / "plan-validation.json"
    digest_path = tmp_path / "digest.json"
    output_path = tmp_path / "proof.json"
    owner = "owner/repository/123/1"
    digest_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "proof": "part4-teardown-authority-digest",
                "result": "PASS",
                "authority_file": authority_path.name,
                "authority_sha256": MODULE.sha256_path(authority_path),
                "run_id": "123",
                "run_attempt": "1",
                "lease_owner": owner,
            }
        ),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def validate_authority(authority, context, inputs, admission, plan_validation):
        captured["inputs"] = inputs
        return {"result": "PASS", "proof": "part4-teardown-authority-verification"}

    monkeypatch.setattr(
        MODULE,
        "validate_part4_contract_file",
        lambda *_args, **_kwargs: SimpleNamespace(contract_sha256="c" * 64),
    )
    monkeypatch.setattr(MODULE, "source_digest", lambda _root: "d" * 64)
    monkeypatch.setattr(MODULE, "validate_authority", validate_authority)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "validate_part4_teardown_authority.py",
            "--repository-root",
            str(tmp_path),
            "--authority",
            str(authority_path),
            "--digest-receipt",
            str(digest_path),
            "--admission-receipt",
            str(admission_path),
            "--apply-plan-json",
            str(tmp_path / "plan.json"),
            "--apply-plan-binary",
            str(tmp_path / "plan.bin"),
            "--apply-plan-validation",
            str(validation_path),
            "--output",
            str(output_path),
            "--repository",
            "owner/repository",
            "--repository-owner",
            "owner",
            "--workflow-name",
            "AWS bounded lab",
            "--event",
            "workflow_dispatch",
            "--ref",
            "refs/heads/main",
            "--actor",
            "owner",
            "--source-commit",
            "a" * 40,
            "--run-id",
            "123",
            "--run-attempt",
            "1",
            "--order-count",
            "500",
            "--budget-ceiling-usd",
            "5",
            "--account-id",
            "857229544428",
            "--region",
            "ap-southeast-2",
            "--oidc-role-arn",
            "arn:aws:iam::857229544428:role/role",
            "--backend-bucket",
            "state-bucket",
            "--backend-key",
            "atlasretail/main.tfstate",
            "--terraform-lock-table",
            "locks",
            "--lease-table",
            "leases",
            "--lease-owner",
            owner,
            "--terraform-version",
            "1.11.4",
        ],
    )

    assert MODULE.main() == 0
    inputs = captured["inputs"]
    assert inputs.contract_id == contract["contract_id"]
    assert inputs.contract_version == contract["version"]
    assert inputs.contract_sha256 == "c" * 64
