from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SCRIPT = SCRIPTS / "validate_phase5_admission.py"
SPEC = importlib.util.spec_from_file_location("validate_phase5_admission", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

COMMIT = "a" * 40
REPOSITORY = "bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform"
REF = "refs/heads/main"


def write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def identity(run_id: str) -> dict[str, object]:
    return {
        "aws_account_id": "857229544428",
        "aws_region": "ap-southeast-2",
        "github_run_id": run_id,
        "oidc_role_arn": "arn:aws:iam::857229544428:role/AtlasRetailGitHubOidcRole",
        "project": "AtlasRetail",
        "ref": REF,
        "repository": REPOSITORY,
        "result": "PASS",
        "run_ceiling_usd": 5,
        "schema_version": "1.0",
        "source_commit": COMMIT,
        "terraform_state_key": "atlasretail/main.tfstate",
    }


def valid_args(tmp_path: Path) -> argparse.Namespace:
    preflight = tmp_path / "preflight"
    glue = tmp_path / "glue"
    plan = tmp_path / "plan"
    write(preflight / "source-identity.json", identity("101"))
    write(
        preflight / "preflight.json",
        {
            "result": "PASS",
            "terraform_state_resources": [],
            "unexpected_resources": [],
            "errors": [],
        },
    )
    write(glue / "source-identity.json", identity("102"))
    write(
        glue / "phase-4-summary.json",
        {
            "result": "PASS",
            "claim": "AWS_GLUE_DEFINITION_CAPABILITY_VERIFIED",
            "source_commit": COMMIT,
            "run_id": "102",
            "workload_started": False,
            "aws_verified": {"independent_cleanup": True},
        },
    )
    write(plan / "source-identity.json", identity("103"))
    write(
        plan / "summary.json",
        {"result": "PASS", "source_commit": COMMIT, "github_run_id": "103"},
    )
    write(
        plan / "terraform-plan-validation.json",
        {
            "result": "PASS",
            "exact_envelope": True,
            "resource_count": 40,
            "read_only_data_source_counts": {"aws_iam_policy_document": 6},
        },
    )
    write(plan / "no-change-verification.json", {"result": "PASS"})
    return argparse.Namespace(
        preflight_dir=preflight,
        glue_probe_dir=glue,
        plan_dir=plan,
        preflight_run_id="101",
        glue_probe_run_id="102",
        plan_run_id="103",
        source_commit=COMMIT,
        repository=REPOSITORY,
        ref=REF,
    )


def test_current_source_prerequisites_pass(tmp_path: Path) -> None:
    result = MODULE.validate(valid_args(tmp_path))

    assert result["result"] == "PASS"
    assert result["errors"] == []


def test_any_stale_or_non_exact_prerequisite_fails_closed(tmp_path: Path) -> None:
    args = valid_args(tmp_path)
    plan = json.loads((args.plan_dir / "terraform-plan-validation.json").read_text())
    plan["exact_envelope"] = False
    write(args.plan_dir / "terraform-plan-validation.json", plan)
    glue = json.loads((args.glue_probe_dir / "phase-4-summary.json").read_text())
    glue["source_commit"] = "b" * 40
    write(args.glue_probe_dir / "phase-4-summary.json", glue)

    result = MODULE.validate(args)

    assert result["result"] == "FAIL"
    assert "plan exact envelope was not enforced" in result["errors"]
    assert "Glue probe source mismatch" in result["errors"]
