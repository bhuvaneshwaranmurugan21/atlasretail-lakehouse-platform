"""Regression coverage for the teardown-authority command boundary."""

from __future__ import annotations

import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "build_part4_teardown_authority", ROOT / "scripts/build_part4_teardown_authority.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
sys.path.pop(0)


def test_command_reads_contract_identity_from_validated_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    admission = tmp_path / "admission.json"
    plan_json = tmp_path / "apply-plan.json"
    plan_binary = tmp_path / "apply-plan.tfplan"
    plan_validation = tmp_path / "apply-plan-validation.json"
    output = tmp_path / "teardown-authority.json"
    digest_output = tmp_path / "teardown-authority-digest.json"
    admission.write_text("{}\n", encoding="utf-8")
    plan_json.write_text("{}\n", encoding="utf-8")
    plan_binary.write_bytes(b"saved-plan")
    plan_validation.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        MODULE,
        "arguments",
        lambda: Namespace(
            repository_root=ROOT,
            admission_receipt=admission,
            apply_plan_json=plan_json,
            apply_plan_binary=plan_binary,
            apply_plan_validation=plan_validation,
            output=output,
            digest_output=digest_output,
            repository="bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform",
            repository_owner="bhuvaneshwaranmurugan21",
            workflow_name="AWS bounded lab",
            event="workflow_dispatch",
            ref="refs/heads/main",
            actor="bhuvaneshwaranmurugan21",
            source_commit="a" * 40,
            run_id="123",
            run_attempt="1",
            order_count=500,
            budget_ceiling_usd=5,
            account_id="857229544428",
            region="ap-southeast-2",
            oidc_role_arn=("arn:aws:iam::857229544428:role/AtlasRetailGitHubOidcRole"),
            backend_bucket="portfolio-lab-tfstate-857229544428-ap-southeast-2",
            backend_key="atlasretail/main.tfstate",
            terraform_lock_table="portfolio-lab-terraform-locks",
            lease_table="portfolio-lab-account-lease",
            lease_owner=("bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/123/1"),
            terraform_version="1.11.4",
        ),
    )
    monkeypatch.setattr(MODULE, "source_digest", lambda _root: "sha256:" + "b" * 64)
    captured: dict[str, Any] = {}

    def build(
        _context: object, inputs: object, *_args: object, **_kwargs: object
    ) -> dict[str, Any]:
        captured["inputs"] = inputs
        return {"result": "PASS"}

    monkeypatch.setattr(MODULE, "build_authority", build)

    assert MODULE.main() == 0
    inputs = captured["inputs"]
    assert inputs.contract_id == "atlasretail-part4-bounded-execution"
    assert inputs.contract_version == "1.1.0"
    assert len(inputs.contract_sha256) == 64
    assert json.loads(output.read_text(encoding="utf-8"))["result"] == "PASS"
    assert json.loads(digest_output.read_text(encoding="utf-8"))["result"] == "PASS"
