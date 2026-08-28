from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TARGET_PATH = ROOT / ".github" / "atlas-target.json"
WORKFLOWS = ROOT / ".github" / "workflows"
OLD_ACCOUNT = "887" + "720" + "497" + "919"
OLD_REGION = "ap-" + "south-1"
PINNED_CREDENTIALS_ACTION = (
    "aws-actions/configure-aws-credentials@e6de054238d6b7531b4efff3b6587d9aade6a06c"
)


def target() -> dict[str, object]:
    return json.loads(TARGET_PATH.read_text(encoding="utf-8"))


def workflow(path: str) -> dict[str, object]:
    return yaml.load((WORKFLOWS / path).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_target_is_exact_and_derivations_are_consistent() -> None:
    value = target()
    account = value["aws_account_id"]
    region = value["aws_region"]
    role = value["oidc_role_name"]

    assert value["repository"] == "bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform"
    assert value["branch_ref"] == "refs/heads/main"
    assert value["oidc_role_arn"] == f"arn:aws:iam::{account}:role/{role}"
    assert value["oidc_provider_arn"] == (
        f"arn:aws:iam::{account}:oidc-provider/token.actions.githubusercontent.com"
    )
    assert value["terraform_state_bucket"] == f"portfolio-lab-tfstate-{account}-{region}"
    assert value["terraform_state_key"] == "atlasretail/main.tfstate"
    assert value["run_ceiling_usd"] == 5
    assert value["monthly_budget_usd"] == 20


def test_loader_validates_repository_variables_and_github_context() -> None:
    value = target()
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/load_aws_target.py",
            "--expect-role-arn",
            str(value["oidc_role_arn"]),
            "--expect-region",
            str(value["aws_region"]),
            "--expect-repository",
            str(value["repository"]),
            "--expect-ref",
            str(value["branch_ref"]),
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_loader_writes_validated_source_identity(tmp_path: Path) -> None:
    value = target()
    source_commit = "a" * 40
    source_identity = tmp_path / "nested" / "source-identity.json"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/load_aws_target.py",
            "--source-identity",
            str(source_identity),
            "--source-commit",
            source_commit,
            "--github-run-id",
            "123456789",
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
    assert json.loads(source_identity.read_text(encoding="utf-8")) == {
        "schema_version": "1.0",
        "project": "AtlasRetail",
        "result": "PASS",
        "source_commit": source_commit,
        "github_run_id": "123456789",
        "repository": value["repository"],
        "ref": value["branch_ref"],
        "aws_account_id": value["aws_account_id"],
        "aws_region": value["aws_region"],
        "oidc_role_arn": value["oidc_role_arn"],
        "terraform_state_key": value["terraform_state_key"],
        "run_ceiling_usd": value["run_ceiling_usd"],
    }


@pytest.mark.parametrize(
    ("source_commit", "github_run_id"),
    (("not-a-commit", "123"), ("a" * 40, "0"), ("a" * 40, "run-123")),
)
def test_loader_rejects_invalid_source_identity(
    tmp_path: Path, source_commit: str, github_run_id: str
) -> None:
    source_identity = tmp_path / "source-identity.json"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/load_aws_target.py",
            "--source-identity",
            str(source_identity),
            "--source-commit",
            source_commit,
            "--github-run-id",
            github_run_id,
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode != 0
    assert not source_identity.exists()


def test_active_aws_workflows_load_the_target_and_pin_credentials_action() -> None:
    names = {
        "aws-bounded-lab.yml",
        "aws-controlled-deployment.yml",
        "aws-glue-service-probe.yml",
        "aws-iam-baseline.yml",
        "aws-oidc-identity.yml",
        "aws-plan-only.yml",
        "aws-read-only-preflight.yml",
        "foundation.yml",
    }
    for name in names:
        content = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert "python scripts/load_aws_target.py" in content
        assert PINNED_CREDENTIALS_ACTION in content

    assert (WORKFLOWS / "aws-bounded-lab.yml").read_text().count("id: target") == 2
    assert (WORKFLOWS / "aws-controlled-deployment.yml").read_text().count("id: target") == 2


def test_plan_and_preflight_are_manual_only() -> None:
    for name in ("aws-plan-only.yml", "aws-read-only-preflight.yml"):
        assert set(workflow(name)["on"]) == {"workflow_dispatch"}


def test_identity_workflow_is_exact_and_sts_only() -> None:
    content = (WORKFLOWS / "aws-oidc-identity.yml").read_text(encoding="utf-8")
    triggers = workflow("aws-oidc-identity.yml")["on"]
    paths = set(triggers["push"]["paths"])

    assert {".github/atlas-target.json", "scripts/load_aws_target.py"} <= paths
    assert '--expect-role-arn "${{ vars.AWS_ROLE_ARN }}"' in content
    assert '--expect-region "${{ vars.AWS_REGION }}"' in content
    assert '--expect-repository "${GITHUB_REPOSITORY}"' in content
    assert '--expect-ref "${GITHUB_REF}"' in content
    assert content.count("aws sts get-caller-identity") == 2
    assert "aws glue " not in content
    assert "aws cloudformation " not in content
    assert "terraform " not in content


def test_active_configuration_has_no_legacy_target_literals() -> None:
    allowed_roots = (
        ROOT / "docs" / "incidents",
        ROOT / "evidence" / "incidents",
    )
    violations: list[str] = []
    for path in ROOT.rglob("*"):
        if (
            not path.is_file()
            or ".git" in path.parts
            or ".venv" in path.parts
            or ".pytest_cache" in path.parts
            or "__pycache__" in path.parts
        ):
            continue
        if any(path.is_relative_to(allowed) for allowed in allowed_roots):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if OLD_ACCOUNT in content or OLD_REGION in content:
            violations.append(path.relative_to(ROOT).as_posix())
    assert violations == []


def test_legacy_rescue_material_is_preserved_but_not_executable() -> None:
    archive = ROOT / "docs" / "incidents" / "legacy"
    assert not (WORKFLOWS / "aws-rescue-teardown.yml").exists()
    assert not (ROOT / ".github" / "atlas-lab-authorizations").exists()
    archived_workflow = (archive / "aws-rescue-teardown.yml").read_text(encoding="utf-8")
    assert OLD_ACCOUNT in archived_workflow
    assert OLD_REGION in archived_workflow
    assert len(list((archive / "authorizations").glob("*.json"))) == 5


def test_static_aws_documents_match_the_current_target() -> None:
    value = target()
    region = str(value["aws_region"])
    account = str(value["aws_account_id"])
    bucket = str(value["terraform_state_bucket"])
    terraform = (ROOT / "infra" / "atlas" / "variables.tf").read_text(encoding="utf-8")
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    iam = (ROOT / "infra" / "iam" / "atlasretail-github-role-policy.json").read_text()
    trust = (ROOT / "infra" / "iam" / "atlasretail-github-role-trust-policy.json").read_text()
    bootstrap = (ROOT / "infra" / "foundation" / "bootstrap-policy.json").read_text()

    assert f'default     = "{region}"' in terraform
    assert f'var.aws_region == "{region}"' in terraform
    assert f"--regions {region}" in ci
    assert f"arn:aws:iam::{account}:role/AtlasRetailGitHubOidcRole" in iam
    assert f"arn:aws:iam::{account}:oidc-provider/token.actions.githubusercontent.com" in trust
    assert bucket in iam
    assert bucket in bootstrap
